# Nurse Licensure Compact API — Product Requirements Document

## 1. Introduction

Hospitals that employ nurses across state lines operate under two overlapping regimes: the Nurse Licensure Compact, which lets a nurse holding a multistate license from her primary state of residence practice in any other compact state, and the facility's own credentialing obligations — primary-source verification at hire, certification tracking (BLS, ACLS, and specialty credentials), annual competency requirements, and disciplined handling of board actions. When any one of these lapses, the exposure is concrete: a nurse scheduled onto a unit without current credentials is a survey deficiency waiting to be written up, and discovering the lapse during a regulatory audit rather than before it is the difference between a corrective action plan and a citation.

This document specifies a credentialing API, mounted under `/credentialing`, that keeps every nurse's practice authority continuously derived rather than periodically remembered. The system tracks state licenses and their primary-source verifications, certifications, competency requirements and completions, disciplinary actions, and travel-nurse credential packets. From those records it derives two gating quantities per nurse — a multistate privilege determination and a credential posture — and lets those derivations drive operations directly: when a nurse's posture slips away from `CLEAR`, her future shifts are cancelled and her approved packets voided atomically within the same trigger, with no intermediate visible state. A logical clock plus an explicit expiry-sweep checkpoint make time deterministic and testable, and a survey-audit subsystem samples completed shifts, issues findings, and projects deficiency counts the way an external surveyor would, so the compliance office can rehearse the audit before the auditor arrives.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. When either header is absent, or when the role value is not one of the roles declared below, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A well-formed request whose declared role lacks permission for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Six roles are declared. `CredentialingSpecialist` is the credentialing office staff who assemble and review credential records, packets, and renewals. `PrimarySourceVerifier` is the independent verifier performing primary-source checks and license attestation, segregated from record creators. `NurseManager` is the nursing unit manager who owns units, scheduling, and competency sessions. `ComplianceOfficer` is the compliance office role that owns disciplinary actions, revocations, surrenders, requirement configuration, and survey audits. `Nurse` is the credentialed nurse acting on her own records. `SystemOperator` is the operations principal driving the logical clock and the expiry checkpoint.

When `X-User-Role` is `Nurse`, `X-User-ID` is the `id` of the acting `Nurse`. Ownership checks on any resource that references a nurse — a credential packet, a packet item, a competency completion — compare the resource's nurse foreign key (its `nurse_id`, or the owning packet's nurse) to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403).

For the five remaining roles — `CredentialingSpecialist`, `PrimarySourceVerifier`, `NurseManager`, `ComplianceOfficer`, and `SystemOperator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it for accountability — as `created_by_user_id` on licenses, packets, and audit runs; `verified_by_user_id` on attested licenses; `requested_by_user_id` and `resolved_by_user_id` on primary-source verifications; `reported_by_user_id`, `acknowledged_by_user_id`, and `adjudicated_by_user_id` on disciplinary actions; `reviewed_by_user_id` on packets; and `submitted_by_user_id` on packet items — but it never compares these values to any entity's `id`. Segregation-of-duties rules instead compare these recorded identifiers against the acting `X-User-ID` of a later step, as detailed throughout §3.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination and List Ordering

All list endpoints accept the `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Out-of-range values are clamped to the nearest bound rather than rejected — a `limit` below 1 reads as 1, a `limit` above 100 reads as 100, and a negative `offset` reads as 0 — while a non-integer `limit` or `offset` is `ERR_INVALID_REQUEST` (400). List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`; `has_more` is true exactly when `offset` plus the number of rows returned is less than `total_count`. Rows are always returned in creation order — `created_at` ascending — and rows that share a single clock instant keep their insertion sequence. No selector, ranking, or tie-break anywhere in the system uses the random `id` field.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries four common properties: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits; `updated_at`, refreshed on every mutation; and `version`, an integer that increments on every mutation of the row. One deliberate exception exists: `PrivilegeEvaluation` is an append-only event log whose rows carry only `id` and `created_at` — both `updated_at` and `version` are absent, and rows are never modified once written. A narrower qualification covers the nurse row: rewrites of the four derived fields performed by the §2.8 recompute fabric stamp `updated_at` and `version` only as §2.8 specifies, so an embedded re-derivation that moves only the privilege fields can persist without advancing either.

Creating a new resource returns HTTP 201 with the created resource in the data field; operations that modify an existing resource return HTTP 200 with the updated resource.

### 2.5. The Logical Clock and Inclusive Expiry Semantics

Every date comparison in the system — expiry, verification freshness, scheduling horizons, audit windows — reads a single logical clock, never the wall clock. Before the clock is ever set, it reads exactly 2026-08-01T00:00:00Z. A `SystemOperator` moves the clock through the test-driving clock capability, which accepts a `to_iso8601` instant and answers with the new `current_utc`. Setting the clock mutates no entity: licenses, certifications, and completions do not expire merely because the clock advanced past their dates. Time-based transitions happen only through the expiry-sweep checkpoint described in §3.9, which keeps every sweep idempotent at a fixed clock.

Expiry is inclusive throughout the platform: a license, certification, or competency completion is valid through its `expires_on` date inclusive, and lapses only when the current date is strictly after `expires_on`. A credential whose `expires_on` equals the current date is still valid on that day.

### 2.6. Numeric Precision and Rounding

Percentages and hour totals are stored at 2 decimal places, rounded half up: this covers each assignment's `hours`, a unit's `scheduled_hours_total`, and the two audit rates `point_in_time_rate` and `shift_incidence_rate`. The packet `readiness_score` is stored at 4 decimal places, rounded half up. The survey deficiency projection rounds each unit stratum to 2 decimal places half up first, then rounds the sum of the already-rounded strata to a whole number, half up. The weekly hours cap compares whole minutes only — never the rounded displayed hours. Expiry-bucket math uses integer day differences, and competency expiry computation produces whole ISO dates with no time component.

### 2.7. Optimistic Concurrency Control on Nurse Writes

Two write operations are guarded by optimistic concurrency control on the nurse record, and both require a non-optional `expected_nurse_version` input carrying the nurse `version` the client last observed.

The first is `PATCH /credentialing/nurses/{nurseId}`, the nurse profile patch. If `expected_nurse_version` does not equal the nurse's current `version` — because the record has advanced since the client last read it, for example through a posture flip, a discipline adjudication, or a sweep-appended evaluation that the client has not observed — the update is rejected with `ERR_STALE_VERSION` (HTTP 412).

The second is `POST /credentialing/privilege-evaluations`, the explicit multistate privilege evaluation. Each successful evaluation legitimately supersedes the prior current determination, because the evaluation log is append-only; a stale base version therefore means the caller evaluated privileges against an out-of-date license and discipline picture. A mismatch with the nurse's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

No endpoint outside these two accepts a version field. Both guarded operations increment the nurse's `version` by exactly 1 on success.

### 2.8. Derived Nurse State and the Recompute Fabric

Four nurse fields are computed, never written directly: `credential_posture`, the gating axis of `CLEAR`, `SCHEDULING_SUSPENDED`, or `PRACTICE_RESTRICTED`; `multistate_privilege_status`, one of `ELIGIBLE_MULTISTATE`, `SINGLE_STATE_ONLY`, or `NONE`; `practice_scope`, a sorted list of state codes the nurse may practice in, empty when the status is `NONE`; and `open_encumbrance_count`, the count of the nurse's disciplinary actions standing `ADJUDICATED`.

Privilege derivations are journaled. Whenever an embedded re-derivation changes the nurse's privilege status or scope, a `PrivilegeEvaluation` row is appended with a `trigger_reason` of `PSOR_CHANGE`, `LICENSE_CHANGE`, `DISCIPLINE_CHANGE`, or `SWEEP`, capturing the `resulting_status`, the sorted `resulting_scope` (the full compact state list when the nurse is `ELIGIBLE_MULTISTATE`), and the `home_license_id` chosen by the home-license selector — null when no home license is eligible. An explicit evaluation always appends its row with `trigger_reason` `MANUAL`, whether or not anything moved.

The credential posture recomputes on every license, certification, completion, or disciplinary-action creation or transition; on shift creation, cancellation, or auto-cancellation; on privilege evaluation; on every nurse profile patch, including a primary-state-of-residence change; on nurse activation; and on each expiry sweep. Consistency is immediate: every mutation and the cascades it triggers commit atomically within the request — or within the sweep run — that caused them.

Derived-field stamping follows these rules. A posture recompute that changes the stored posture stamps the nurse — `updated_at` refreshed and `version` incremented by 1 — and one that leaves the posture unchanged does not stamp her. An embedded privilege re-derivation that moves the privilege fields does not by itself stamp the nurse, except that a sweep stamps every nurse for whom it appends a `SWEEP` evaluation, and a sustained adjudication or a resolution always stamps her once for the encumbrance-count move, in addition to any posture-flip stamp from the same trigger.

### 2.9. Validation Pipeline and Error Precedence

Every request flows through a single ordered validation pipeline, and a request violating several checks receives the error from the earliest stage it fails. The stages, in evaluation order:

1. **Identity headers** — both headers present and the role value declared, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Role authorization** — the declared role must be permitted for the endpoint, else `ERR_FORBIDDEN_ROLE` (403).
3. **Entity-backed ownership** — a `Nurse`-role caller may act only on resources she owns: her own packets at submission, her own packet items at evidence submission, and her own completions at recording. A violation is `ERR_OWNERSHIP_VIOLATION` (403). The comparison runs against the loaded target, so at packet submission and evidence submission an unresolvable path id is `ERR_NOT_FOUND` before ownership is ever compared, and at completion recording the request body's own well-formedness is established first, so a malformed body is `ERR_INVALID_REQUEST` before the ownership comparison.
4. **Path existence** — path resource ids must exist, validated left to right, else `ERR_NOT_FOUND` (404).
5. **Body referential integrity** — foreign keys in the payload must resolve: `nurse_id` (`ERR_NURSE_NOT_FOUND`), `license_id` (`ERR_LICENSE_NOT_FOUND`), `unit_id` or `target_unit_id` (`ERR_UNIT_NOT_FOUND`), and `requirement_id` (`ERR_REQUIREMENT_NOT_FOUND`), all 404. Cross-row consistency follows within this stage: a `license_id` belonging to a different nurse than the payload's `nurse_id` is `ERR_CROSS_NURSE_REFERENCE` (422); a requirement whose `applies_to` omits the nurse's employment type is `ERR_REQUIREMENT_NOT_APPLICABLE` (422); and malformed requests — a missing required field, a type mismatch, an unknown field, an invalid enum value, or a missing conditional field such as `discrepancy_note`, `rejection_reason`, `resolution_note`, or the `license_id` of a `LICENSE`-scope action — are `ERR_INVALID_REQUEST` (400).
6. **Optimistic concurrency** — endpoints declaring `expected_nurse_version` require it to equal the nurse's current `version`, else `ERR_STALE_VERSION` (412).
7. **State validity** — the target entity must stand in a valid from-state for the requested transition, reported per entity as `ERR_INVALID_LICENSE_STATE`, `ERR_INVALID_PSV_STATE`, `ERR_INVALID_CERTIFICATION_STATE`, `ERR_INVALID_DISCIPLINE_STATE`, `ERR_INVALID_PACKET_STATE`, `ERR_INVALID_ITEM_STATE`, `ERR_INVALID_SHIFT_STATE`, `ERR_INVALID_AUDIT_STATE`, `ERR_INVALID_FINDING_STATE`, `ERR_INVALID_NURSE_STATE`, or `ERR_INVALID_BOOKING_STATE` (all 409). State gates on related entities live here too: disciplinary-action creation and shift creation require the nurse `ACTIVE` (`ERR_INVALID_NURSE_STATE`), and shift creation additionally requires the posture `CLEAR` (`ERR_NURSE_NOT_CLEAR`, 409). Packet approval's nurse-`ACTIVE` and posture-`CLEAR` gates are the exception: they evaluate after approval's segregation and completeness checks, as §3.7 pins.
8. **Safety and compliance** — segregation-of-duties user checks (`ERR_SEGREGATION_OF_DUTIES`, 403), unit certification prerequisites at booking (`ERR_UNIT_CERT_REQUIREMENT_UNMET`, 403), verification freshness at attestation and renewal (`ERR_PSV_STALE`, 422) — at renewal the stage-10 window rule is examined first, as §3.2 pins — compact-state eligibility of a multistate flag (`ERR_MULTISTATE_NON_COMPACT_STATE`, 422), activation prerequisites (`ERR_HIRE_REQUIREMENTS_UNMET`, 409), and packet-item evidence checks (`ERR_ITEM_EVIDENCE_INVALID`, 422).
9. **Constraint satisfaction** — shift overlap (`ERR_SHIFT_OVERLAP`, 409), session capacity (`ERR_SESSION_FULL`, 409), duplicate booking (`ERR_BOOKING_DUPLICATE`, 409), one active packet per nurse (`ERR_ACTIVE_PACKET_EXISTS`, 409), packet item completeness (`ERR_PACKET_ITEMS_INCOMPLETE`, 409), waivability (`ERR_ITEM_NOT_WAIVABLE`, 422), audit closure with open findings (`ERR_AUDIT_FINDINGS_OPEN`, 409), uniqueness of the nurse email, the state-plus-license-number pair, the requirement code, and the unit name (`ERR_DUPLICATE_RESOURCE`, 409), and booking deletion after attendance (`ERR_INVALID_BOOKING_STATE`, 409).
10. **Temporal rules** — a shift starting in the past (`ERR_SHIFT_IN_PAST`), a shift beyond the scheduling horizon (`ERR_SCHEDULING_HORIZON_EXCEEDED`), a start attempted outside its window (`ERR_SHIFT_NOT_STARTABLE`), inverted or retrograde date ranges (`ERR_INVALID_DATE_RANGE`), future-dated discipline (`ERR_DISCIPLINE_EFFECTIVE_FUTURE`), premature resolution (`ERR_RESOLUTION_PREMATURE`), a renewal window not yet open (`ERR_RENEWAL_WINDOW_NOT_OPEN`), and session completion before the session has ended (`ERR_SESSION_NOT_ENDED`) — all 422.
11. **Labor budget** — the weekly hours cap, `ERR_WEEKLY_HOURS_EXCEEDED` (422).

## 3. Business Logic & Workflows

### 3.1. Bringing a Nurse On Board: Profile, Activation, and Termination

A `CredentialingSpecialist` opens a nurse record with `full_name`, a work `email` (unique across nurses — a duplicate is `ERR_DUPLICATE_RESOURCE`), `primary_state_of_residence` (the PSOR, a two-letter state code that drives compact privilege derivation), `employment_type` (one of `STAFF`, `TRAVEL`, or `PER_DIEM`), and `hire_date` (an ISO date). A new nurse stands `ONBOARDING`, with `credential_posture` `SCHEDULING_SUSPENDED` and `multistate_privilege_status` `NONE`. Creation runs an initial privilege derivation so `practice_scope` reflects whatever the derivation yields, but no `PrivilegeEvaluation` row is appended at this point.

Profile maintenance goes through the nurse profile patch, which accepts optional `full_name`, `email`, `primary_state_of_residence`, and `employment_type` alongside the mandatory concurrency guard field described in §2.7, and increments the nurse's `version` by 1 on success. Every patch — with or without a PSOR change — recomputes posture (an `employment_type` change can shift which mandatory requirements apply), and the version still increments by exactly 1 even when the recompute flips the posture and fires the §3.5 cascade. Changing the PSOR re-derives compact privilege immediately: when the derived status or scope moves, a `PrivilegeEvaluation` with `trigger_reason` `PSOR_CHANGE` is appended and the nurse's privilege fields are updated, followed by the posture recompute.

Activation moves the nurse from `ONBOARDING` to `ACTIVE` and is allowed only from `ONBOARDING` — activating from any other state yields `ERR_INVALID_NURSE_STATE`. Two hiring prerequisites must hold, both reported as `ERR_HIRE_REQUIREMENTS_UNMET`: at least one of the nurse's state licenses stands `ACTIVE`, and the derived `practice_scope` contains the facility state (§3.5). Activation triggers a posture recompute, so a nurse may become `ACTIVE` yet remain `SCHEDULING_SUSPENDED` while BLS or competency evidence is still missing.

Termination moves a nurse from either `ONBOARDING` or `ACTIVE` to `TERMINATED`; terminating an already `TERMINATED` nurse is rejected with `ERR_INVALID_NURSE_STATE`. Termination cascades within the same request. Every shift assignment still `SCHEDULED` whose start lies in the future is auto-cancelled — its status becomes `AUTO_CANCELLED` with `cancel_reason` `NURSE_TERMINATED` — and each such cancellation decrements its unit's `scheduled_hours_total` by the assignment's `hours` and its `active_assignment_count` by 1. Every credential packet in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED` moves to `VOIDED`. The nurse's `credential_posture` is forced to `SCHEDULING_SUSPENDED` as the terminal snapshot.

### 3.2. The State License Lifecycle: Verification, Attestation, Renewal, and Surrender

Licenses are registered by a `CredentialingSpecialist` with the owning `nurse_id`, the issuing `state_code`, a `license_number` (the state-code-plus-license-number pair must be unique, else `ERR_DUPLICATE_RESOURCE`), a `license_class` of `RN` or `APRN`, a `multistate_flag`, `issued_on`, and `expires_on`. Setting `multistate_flag` true is allowed only when the `state_code` belongs to the compact state set of §3.3; otherwise creation fails with `ERR_MULTISTATE_NON_COMPACT_STATE`. A license is born `DRAFT`, and its creator is recorded in `created_by_user_id` for later segregation checks.

The verification path runs `DRAFT` → `PENDING_VERIFICATION` → `VERIFIED` → `ACTIVE`. Submission to verification is allowed only from `DRAFT`, else `ERR_INVALID_LICENSE_STATE`. A `CredentialingSpecialist` then requests a primary-source verification naming the `license_id` and a `channel` of `NURSYS`, `BOARD_PORTAL`, or `MANUAL_REVIEW`. A verification may be requested for a license standing `PENDING_VERIFICATION`, `VERIFIED`, or `EXPIRED`; against any other license state the request is rejected with `ERR_INVALID_LICENSE_STATE`. The verification is born `REQUESTED`, with the requester captured in `requested_by_user_id`.

A `PrimarySourceVerifier` records the `outcome` of a verification from `REQUESTED` — from any other state the attempt is `ERR_INVALID_PSV_STATE` — and the recorder must differ from the requester, else `ERR_SEGREGATION_OF_DUTIES`; the recorder is stamped into `resolved_by_user_id`. Three outcomes exist. `VERIFIED` sets `verified_on` to the current clock date and `valid_through` to `verified_on` plus 180 days, and — when the underlying license stands `PENDING_VERIFICATION` — moves the license to `VERIFIED`; recording a verified outcome against a license already `VERIFIED` or `EXPIRED` leaves the license state untouched. `DISCREPANCY` requires a `discrepancy_note` (an absent note is `ERR_INVALID_REQUEST`; the note is optional for the other outcomes) and returns a `PENDING_VERIFICATION` license to `DRAFT`. `UNREACHABLE` changes nothing on the license, and a fresh verification may simply be requested again.

Attestation promotes a license from `VERIFIED` to `ACTIVE` and is performed by a `PrimarySourceVerifier` who must not be the specialist who created the record: the acting user's id is compared against `created_by_user_id`, and a match is `ERR_SEGREGATION_OF_DUTIES`. The attester is stamped into `verified_by_user_id`, which stays null until attestation. Attestation also requires a fresh verification on file — at least one verification row in `VERIFIED` status whose `valid_through` is on or after the current date. The freshness boundary is inclusive: a verification whose `valid_through` equals the current date still counts. With no `VERIFIED` verification at all, or with every `VERIFIED` verification stale, attestation fails with `ERR_PSV_STALE`. A successful attestation re-derives the nurse's compact privilege, appending a `LICENSE_CHANGE` evaluation when the result moved, and recomputes her posture.

Renewal brings an `EXPIRED` license back to life, and — as a proactive path — may also be invoked on an `ACTIVE` license whose expiry is at most 60 days away. An `ACTIVE` license further from expiry than 60 days rejects with `ERR_RENEWAL_WINDOW_NOT_OPEN`, and a license in any state other than `EXPIRED` or window-eligible `ACTIVE` rejects with `ERR_INVALID_LICENSE_STATE`. The renewal's remaining rules then evaluate in this order: first the same fresh-verification rule as attestation, else `ERR_PSV_STALE`; then `new_expires_on`, which must be strictly after the current date, else `ERR_INVALID_DATE_RANGE`. A successful renewal writes the license's `expires_on` to `new_expires_on` and lands the license in `ACTIVE` — unless a disciplinary action with `LICENSE` scope naming this license stands `ADJUDICATED`, in which case the renewal lands in `ENCUMBERED` instead and the license stays encumbered until the discipline is resolved (§3.8). Either landing re-derives privilege (a `LICENSE_CHANGE` row when changed) and recomputes posture.

Licenses are also encumbered and released by the discipline workflow itself: adjudicating a `LICENSE`-scope `SUSPENSION` or `REVOCATION` moves the named license from `ACTIVE` to `ENCUMBERED`, and resolving that action returns it to `ACTIVE` when its `expires_on` is on or after the current date, or to `EXPIRED` when that date has already passed (§3.8). Independently, the expiry sweep moves both `ACTIVE` and `ENCUMBERED` licenses whose `expires_on` has passed to `EXPIRED` (§3.9); for an encumbered license this is purely an expiry transition — the practice restriction persists while the adjudicated discipline remains open, because the encumbrance, not the expiry, drives it. Finally, a `ComplianceOfficer` may surrender a license from any status other than `SURRENDERED` — attempting surrender on a surrendered license is `ERR_INVALID_LICENSE_STATE` — and `SURRENDERED` is terminal. Every surrender re-derives privilege (a `LICENSE_CHANGE` row when changed) and recomputes posture.

### 3.3. Multistate Privilege: The Compact Derivation

The compact state set contains eight states: `AZ`, `CO`, `FL`, `GA`, `MD`, `NC`, `TN`, and `TX`. The facility itself sits in `TX`, which is why that state's presence in a nurse's scope gates both activation and a clear posture.

Privilege derivation begins with the home-license selector. Among the nurse's licenses standing `ACTIVE` whose `state_code` equals her `primary_state_of_residence`, the home license is the one with the latest `expires_on`; ties break toward the earliest `created_at`. Separately, an open privilege encumbrance exists whenever the nurse has a disciplinary action with `scope` `PRIVILEGE` standing `ADJUDICATED`. The derivation then runs exactly three branches:

- When a home license exists, its `multistate_flag` is true, the PSOR is one of the compact states, and no open privilege encumbrance exists, the nurse is `ELIGIBLE_MULTISTATE` and her scope is the full compact state list, sorted ascending.
- When all of the above holds except that an open privilege encumbrance exists, she degrades to `SINGLE_STATE_ONLY` with a scope narrowed to exactly her primary state of residence.
- Otherwise, the nurse derives from whatever `ACTIVE` licenses she holds: the scope is the sorted, distinct set of those licenses' `state_code` values; with at least one such license the status is `SINGLE_STATE_ONLY`, and with none it is `NONE` and the scope is the empty list.

A `CredentialingSpecialist` may force an explicit evaluation at any time by supplying the `nurse_id` together with the concurrency guard field of §2.7. The explicit evaluation always appends a `PrivilegeEvaluation` with `trigger_reason` `MANUAL`, updates `multistate_privilege_status` and `practice_scope` on the nurse, increments the nurse's `version` by 1, recomputes posture, and responds 201 with the appended evaluation row. Embedded derivations — fired by license transitions, discipline transitions, PSOR changes, and the sweep — append a row only when the status or scope actually changed, and recompute posture in all cases. As §3.8 details, adjudicating a `PRIVILEGE`-scope action drives an `ELIGIBLE_MULTISTATE` nurse down to `SINGLE_STATE_ONLY` confined to her PSOR with a `DISCIPLINE_CHANGE` row appended, and resolving that action re-derives and restores her prior standing, again under `DISCIPLINE_CHANGE`.

### 3.4. Certifications, Competency Requirements, and Completions

A `CredentialingSpecialist` records a certification with `nurse_id`, a `cert_type` of `BLS`, `ACLS`, `PALS`, `CCRN`, `CNOR`, or `OCN`, the `issuing_body`, `obtained_on`, and `expires_on`. A certification is born `ACTIVE`, and its creation recomputes the nurse's posture. Certifications expire only through the sweep: an `ACTIVE` certification whose `expires_on` has passed becomes `EXPIRED`; every packet item sourced from it standing `VERIFIED` flips to `INVALIDATED`; the owning packets' readiness scores recompute; any such packet standing `APPROVED` moves to `VOIDED`; and the nurse's posture recomputes. Renewal moves a certification from `EXPIRED` back to `ACTIVE` — renewal from any other state is `ERR_INVALID_CERTIFICATION_STATE` — with a `new_expires_on` strictly after the current date, else `ERR_INVALID_DATE_RANGE`. Renewal recomputes posture but does not resurrect invalidated packet items; those need fresh evidence. A `ComplianceOfficer` may revoke a certification from `ACTIVE` or `EXPIRED` — any other state is `ERR_INVALID_CERTIFICATION_STATE` — landing it in terminal `REVOKED`. Revoking an `ACTIVE` certification fires the same item-invalidation cascade as expiry; both the revoke and the expire paths recompute the nurse's posture.

Competency requirements are configuration, authored by a `ComplianceOfficer`: a unique `code` (a duplicate is `ERR_DUPLICATE_RESOURCE`), a display `name`, `validity_months` in whole months (used by rolling mode), a `window_mode` of `ROLLING` or `FISCAL`, a `mandatory` flag (mandatory requirements gate credential posture), and `applies_to`, the subset of employment types — drawn from `STAFF`, `TRAVEL`, and `PER_DIEM` — that the requirement covers.

Recording a completion takes `nurse_id`, `requirement_id`, and `completed_on`. The requirement must exist, else `ERR_REQUIREMENT_NOT_FOUND`; its `applies_to` must contain the nurse's employment type, else `ERR_REQUIREMENT_NOT_APPLICABLE`; and `completed_on` must not lie in the future, else `ERR_INVALID_DATE_RANGE`. Nurses may record their own completions, and a nurse supplying another nurse's id is `ERR_OWNERSHIP_VIOLATION`; a `CredentialingSpecialist` may record for anyone. A completion is born `CURRENT` with `source` `MANUAL` — or `SESSION` when produced by a session booking, in which case `session_booking_id` links back to that booking and stays null otherwise. Its `expires_on` is computed by mode. Under `ROLLING`, expiry is the anniversary of `completed_on` plus `validity_months` months, keeping the same day of month; when the target month lacks that day, the target month's last day is used. Under `FISCAL`, expiry is the first occurrence of the fiscal-year end, June 30, that falls on or after `completed_on` — so a completion dated exactly June 30 expires that same day. A completion remains `CURRENT` while the current date is on or before its `expires_on`; the sweep lapses it once the date has passed. Creating a new completion for the same nurse and requirement supersedes the prior rows — whether they stand `CURRENT` or already `LAPSED`, they become `SUPERSEDED` — and packet items sourced from a superseded completion flip to `INVALIDATED` only when they stand `VERIFIED`, since they may be re-verified against the new completion. Completion creation recomputes posture.

Group training runs through competency sessions. A `NurseManager` creates a session with a `requirement_id`, a `title`, `starts_at`, `ends_at` (strictly after the start, else `ERR_INVALID_DATE_RANGE`), and a `capacity` bounding the number of bookings. Booking a nurse into a session is rejected once the session's `booked_count` has reached `capacity` (`ERR_SESSION_FULL`) and when the same nurse already holds a booking in that session (`ERR_BOOKING_DUPLICATE`); bookings may otherwise overlap freely — aggregate capacity, not scheduling collision, is the constraint. A booking is born with `attended` false, tied to its session by `session_id`, and increments `booked_count` by 1. After the session has ended — completing before `ends_at` is `ERR_SESSION_NOT_ENDED` — marking the booking complete sets `attended` true and creates a linked completion with `source` `SESSION`, `completed_on` set to the session's start date, and the booking's `completion_id` pointing at the new row; the usual supersede and posture recompute follow. Deleting a booking frees a seat by decrementing `booked_count`, and is allowed only while `attended` is still false — otherwise `ERR_INVALID_BOOKING_STATE`. Deletion returns 204 with no body.

### 3.5. Credential Posture: The Derived Scheduling Gate

Posture is the system's enforcement axis, and its evaluation order is pinned. Before anything else is examined, the unit-derived requirement set is snapshotted: the union of `required_cert_types` over every unit holding at least one of this nurse's shift assignments in `SCHEDULED` or `IN_PROGRESS` at that instant. Cancellations fired later within the same evaluation do not shrink this snapshot, so a single trigger cannot oscillate; a later recompute may clear the nurse after remediation. The full requirement set is then the BLS certification, plus every mandatory competency requirement applicable to the nurse's employment type, plus that unit-derived snapshot.

With the requirement set fixed, the ladder below evaluates in order, stopping at the first rung that matches:

1. A nurse whose `status` is not `ACTIVE` — she is onboarding or terminated — is `SCHEDULING_SUSPENDED`.
2. A nurse with any disciplinary action standing `ADJUDICATED` at severity `PROBATION`, `SUSPENSION`, or `REVOCATION` is `PRACTICE_RESTRICTED`.
3. The facility state `TX` must appear in her derived `practice_scope`; when it does not, she is `SCHEDULING_SUSPENDED`.
4. Every certification type in the requirement set must be backed by an `ACTIVE` certification, and every competency requirement in the set by a `CURRENT` completion; any deficit means `SCHEDULING_SUSPENDED`.
5. Otherwise she is `CLEAR`.

When a recompute changes the stored posture, the new value persists. When the flip is away from `CLEAR`, the posture cascade fires exactly once: every shift assignment still `SCHEDULED` with a start after the current instant is auto-cancelled with `cancel_reason` `POSTURE_SCHEDULING_SUSPENDED` or `POSTURE_PRACTICE_RESTRICTED` matching the new posture; each such cancellation decrements its unit's `scheduled_hours_total` and `active_assignment_count`; and every packet standing `APPROVED` moves to `VOIDED`. Assignments already `IN_PROGRESS` are never auto-cancelled.

### 3.6. Scheduling a Nurse: Shift Assignments, Unit Counters, and the Weekly Cap

Units are created by a `NurseManager` with a unique `name` (a duplicate is `ERR_DUPLICATE_RESOURCE`) and an optional `required_cert_types` list, empty by default, naming the certification types a nurse must hold `ACTIVE` to be booked onto — or packet-approved for — that unit. Each unit tracks two computed counters: `scheduled_hours_total`, the sum of `hours` over its assignments in `SCHEDULED` or `IN_PROGRESS`, kept at 2 decimals, and `active_assignment_count`, the number of such assignments.

Booking an assignment takes `nurse_id`, `unit_id`, `starts_at`, and `ends_at`, and its gates evaluate in a fixed order. First the nurse must be `ACTIVE`, else `ERR_INVALID_NURSE_STATE`; then her posture must be `CLEAR`, else `ERR_NURSE_NOT_CLEAR`. Next, every entry of the unit's `required_cert_types` must be backed by an `ACTIVE` certification of that type, else `ERR_UNIT_CERT_REQUIREMENT_UNMET`. The new interval must then not collide with any of the nurse's existing assignments in `SCHEDULED` or `IN_PROGRESS`: intervals are half-open, so one assignment ending exactly when another begins is allowed, while a true collision is `ERR_SHIFT_OVERLAP`. Temporal checks follow — `ends_at` must be strictly after `starts_at` (`ERR_INVALID_DATE_RANGE`); the start date must not precede the current date (`ERR_SHIFT_IN_PAST`); and the start date must not lie beyond the scheduling horizon, 90 days past the current date (`ERR_SCHEDULING_HORIZON_EXCEEDED`). Last, the weekly labor budget below is enforced, and exceeding it is `ERR_WEEKLY_HOURS_EXCEEDED`.

The budget is computed over a rolling seven-calendar-day window: from midnight UTC of the day six days before the new assignment's start date, up to but not including midnight UTC of the day after the start date. The nurse's assignments in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` whose half-open intervals overlap that window contribute their whole-minute durations — an overlap exists when the existing assignment starts before the window's end and the window's start falls before the existing assignment's end — and the new assignment's own whole minutes are added. A total strictly greater than 3,600 minutes, which is 60 hours, is rejected; a total of exactly 3,600 minutes is allowed. The cap always compares integer minutes, never the rounded displayed hours. Each assignment's displayed `hours` are its duration in minutes divided by 60, rounded half up to 2 decimals. A successful booking is born `SCHEDULED`, and its hours and count fold into the unit's `scheduled_hours_total` and `active_assignment_count` immediately.

Starting an assignment moves it from `SCHEDULED` to `IN_PROGRESS` — from any other state the attempt is `ERR_INVALID_SHIFT_STATE` — and requires the current instant inside the half-open window from `starts_at` to `ends_at`; too early or too late is `ERR_SHIFT_NOT_STARTABLE`. The posture gate follows the window check: the nurse's posture must still be `CLEAR` at start, else `ERR_NURSE_NOT_CLEAR`, and a successful start stamps `was_clear_at_start` true — the stamp is guaranteed by the precondition, and the field stays null until the shift starts. Completing moves `IN_PROGRESS` to `COMPLETED` and releases the unit counters: completed assignments leave the counted set, so the unit's `scheduled_hours_total` drops by the assignment's `hours` and `active_assignment_count` by 1. A manager may instead cancel a `SCHEDULED` assignment: the shift lands `CANCELLED` with `cancel_reason` `MANUAL`, the unit counters are released the same way, and the nurse's posture recomputes — the cancelled assignment's unit requirements leave the snapshot set on the next recompute.

### 3.7. Travel-Nurse Credential Packets and the Readiness Score

A `CredentialingSpecialist` assembles a credential packet for a nurse targeting a unit via `nurse_id` and `target_unit_id`, both of which must resolve (else `ERR_NURSE_NOT_FOUND` or `ERR_UNIT_NOT_FOUND`). At most one packet per nurse may stand in `DRAFT`, `SUBMITTED`, or `UNDER_REVIEW` at a time — a second creation is `ERR_ACTIVE_PACKET_EXISTS`. Creation materializes the packet's checklist in a fixed order: a license-verification item, a BLS item, an ACLS item only when the target unit's `required_cert_types` contains `ACLS`, an annual-competency item, and an attestation item. Each item's `item_type` is therefore one of `LICENSE_VERIFICATION`, `BLS`, `ACLS`, `COMPETENCY_ANNUAL`, or `ATTESTATION`; each links to its packet through `packet_id`; each carries a `critical` flag — true for license verification, BLS, the unit-required ACLS, and the annual competency item, false for attestation — and a scoring `weight`: 40 for license verification, 20 each for BLS and ACLS, 15 for the annual competency item, and 5 for attestation. Items are born `MISSING`, the packet is born `DRAFT` with `readiness_score` 0, and the assembler is recorded in `created_by_user_id`.

The owning nurse then supplies evidence item by item. An item in `MISSING` or `INVALIDATED` accepts submission — from any other state the attempt is `ERR_INVALID_ITEM_STATE` — the parent packet must stand in `DRAFT` or `REJECTED` (else `ERR_INVALID_PACKET_STATE`), and a nurse acting on someone else's packet is `ERR_OWNERSHIP_VIOLATION`. Submission records the supplied `evidence_ref`, stamps `submitted_by_user_id`, moves the item to `SUBMITTED`, and recomputes the packet's readiness score.

Verification belongs to a `CredentialingSpecialist` and is allowed only from `SUBMITTED`, else `ERR_INVALID_ITEM_STATE`. The server checks that the underlying evidence actually holds, else `ERR_ITEM_EVIDENCE_INVALID`: a license-verification item requires an `ACTIVE` state license for the nurse; BLS and ACLS items each require an `ACTIVE` certification of that `cert_type`; the annual-competency item requires a `CURRENT` completion for a mandatory applicable requirement; and an attestation item requires only its `evidence_ref`. On success the item becomes `VERIFIED`, the satisfying credential row — the earliest-created row passing the check, when several qualify — is recorded in `source_credential_id` (null for attestation), and the packet's readiness score recomputes. A specialist may instead waive an item standing `MISSING` or `SUBMITTED`, recording a `waive_reason`, but only when the item is not critical — waiving a critical item is `ERR_ITEM_NOT_WAIVABLE`. Waiving lands the item in terminal `WAIVED` and recomputes the score.

The readiness score itself is a weighted ratio. A `VERIFIED` item earns full credit, `WAIVED` earns half credit, `SUBMITTED` earns a quarter credit, and `MISSING` or `INVALIDATED` earns nothing. The raw score is the sum of each item's weight times its credit, divided by the sum of the weights, rounded half up to 4 decimals. A critical cap then applies: while any critical item stands `MISSING` or `INVALIDATED`, the score is the smaller of the raw value and 0.49.

Once the checklist is complete in the loose sense — every item `SUBMITTED`, `VERIFIED`, or `WAIVED`, else `ERR_PACKET_ITEMS_INCOMPLETE` — the owning nurse submits the packet, moving it from `DRAFT` to `SUBMITTED`; the submission action also accepts a packet standing `REJECTED`, and a separate resubmission action moves `REJECTED` to `SUBMITTED` under the same completeness rule. A specialist other than the assembler then starts review, moving `SUBMITTED` to `UNDER_REVIEW` — the segregation check compares the acting user against `created_by_user_id` and rejects a match with `ERR_SEGREGATION_OF_DUTIES`. From `UNDER_REVIEW`, approval runs its gates in this order: the same segregation-from-the-assembler rule (`ERR_SEGREGATION_OF_DUTIES`), then strict completeness — every item `VERIFIED` or `WAIVED`, else `ERR_PACKET_ITEMS_INCOMPLETE` — then a nurse who is `ACTIVE` (`ERR_INVALID_NURSE_STATE`), and finally the posture `CLEAR` (`ERR_NURSE_NOT_CLEAR`); approval stamps `reviewed_by_user_id`. Rejection, also from `UNDER_REVIEW` and under the same segregation rule, requires a `rejection_reason` (absent reason → `ERR_INVALID_REQUEST`) and stamps `reviewed_by_user_id` as well.

Packets are voided, never deleted. An `APPROVED` packet moves to `VOIDED` automatically when the nurse's posture flips away from `CLEAR`, and when any of its items falls from `VERIFIED` to `INVALIDATED`; terminating the nurse voids packets in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, and `APPROVED` alike. Invalidation is itself a cascade: when the credential row named by an item's `source_credential_id` lapses — a license going `EXPIRED`, `ENCUMBERED`, or `SURRENDERED`; a certification going `EXPIRED` or `REVOKED`; a completion going `LAPSED` or `SUPERSEDED` — a `VERIFIED` item becomes `INVALIDATED`, the readiness score recomputes, and an `APPROVED` parent packet is voided. Invalidated items are never auto-restored by later renewals; the nurse re-submits fresh evidence.

### 3.8. Disciplinary Actions and Practice Restriction

A `ComplianceOfficer` reports a disciplinary action with `nurse_id`, `scope`, `action_type`, and `effective_on`. The subject nurse must be `ACTIVE`, else `ERR_INVALID_NURSE_STATE`, and `effective_on` must not lie in the future, else `ERR_DISCIPLINE_EFFECTIVE_FUTURE`. The `scope` is `LICENSE` for an action against one license or `PRIVILEGE` for an action against compact privilege; `license_id` is required exactly when the scope is `LICENSE` and must be absent when it is `PRIVILEGE` — violations are `ERR_INVALID_REQUEST` — and a `license_id` belonging to a different nurse than the payload's `nurse_id` is `ERR_CROSS_NURSE_REFERENCE`. The `action_type` is one of `REPRIMAND`, `PROBATION`, `SUSPENSION`, or `REVOCATION`. The action is born `REPORTED`, with the reporter captured in `reported_by_user_id`.

Acknowledgement moves the action from `REPORTED` to `UNDER_REVIEW` — from any other state the attempt is `ERR_INVALID_DISCIPLINE_STATE` — and stamps `acknowledged_by_user_id`. Adjudication then moves it from `UNDER_REVIEW` to `ADJUDICATED` when the `outcome` is `SUSTAINED`, or to `DISMISSED` when the `outcome` is `DISMISSED`; the adjudicating officer must differ from the acknowledger, else `ERR_SEGREGATION_OF_DUTIES`, and is stamped into `adjudicated_by_user_id`.

A sustained adjudication fires the encumbrance cascade, and each branch is distinct. The nurse's `open_encumbrance_count` increments by 1. When the scope is `LICENSE` and the action type is `SUSPENSION` or `REVOCATION`, the named license moves from `ACTIVE` to `ENCUMBERED`. When the scope is `PRIVILEGE`, the nurse's privilege re-derives downward — `ELIGIBLE_MULTISTATE` becomes `SINGLE_STATE_ONLY` confined to her primary state of residence — with a `DISCIPLINE_CHANGE` evaluation appended. When the action type is `PROBATION`, `SUSPENSION`, or `REVOCATION`, the posture recompute lands her in `PRACTICE_RESTRICTED`, firing the full posture cascade of §3.5: future `SCHEDULED` shifts auto-cancelled with `cancel_reason` `POSTURE_PRACTICE_RESTRICTED`, unit counters decremented per cancellation, and approved packets voided. A sustained `REPRIMAND` changes no license, privilege, or posture — it is record only, though it still counts as an open encumbrance.

Resolution moves the action from `ADJUDICATED` to `RESOLVED` — from any other state, `ERR_INVALID_DISCIPLINE_STATE` — and requires a `resolution_note`, else `ERR_INVALID_REQUEST`. A minimum active period must have elapsed since `effective_on`: none for `REPRIMAND`, 90 days for `PROBATION`, 30 days for `SUSPENSION`, and 365 days for `REVOCATION`; resolving earlier is `ERR_RESOLUTION_PREMATURE`. Resolution decrements `open_encumbrance_count` by 1 and unwinds the encumbrance. A license it encumbered returns from `ENCUMBERED` to `ACTIVE` when its `expires_on` is on or after the current date, or to `EXPIRED` when that date has passed. A `PRIVILEGE`-scope action re-derives the nurse's privilege, restoring her prior standing and appending a `DISCIPLINE_CHANGE` evaluation. And the posture recompute lifts `PRACTICE_RESTRICTED` once this was her last open encumbrance.

### 3.9. Expiry Monitoring and the Ops-Run Sweep

The expiry report is a computed read, available to every role, that answers "what expires when" from dates alone — deliberately independent of sweep-driven statuses. Its response carries `response_type` `object` with `data` shaped as `{"rows": [...]}` and the §2.3 pagination fields in `meta`; `limit` and `offset` apply to the row list. Each row carries `credential_kind` (`LICENSE`, `CERTIFICATION`, or `COMPLETION`), `credential_id`, `nurse_id`, `expires_on`, `days_to_expiry`, `bucket`, and `created_at`. For each credential row it computes `days_to_expiry`, the whole-day difference from the current date to the row's `expires_on`, negative once the date has passed, and buckets it: `EXPIRED` when the difference is negative, `CRITICAL` from zero up to and including 30 days, `WARNING` beyond 30 up to and including 60 days, and `OK` beyond 60. The report includes licenses in `VERIFIED`, `ACTIVE`, `ENCUMBERED`, or `EXPIRED` — never `DRAFT` or `PENDING_VERIFICATION` — certifications in `ACTIVE` or `EXPIRED` (never `REVOKED`), and completions in `CURRENT` or `LAPSED` (never `SUPERSEDED`). An optional `nurse_id` narrows the report to one nurse, and rows sort by `days_to_expiry` ascending, ties broken by `created_at` ascending.

The sweep, run by a `SystemOperator`, is the only path that turns the passage of time into state changes, and it applies its transitions in a pinned order. First, licenses standing `ACTIVE` or `ENCUMBERED` whose `expires_on` has passed move to `EXPIRED`, firing the packet-item invalidation cascade of §3.7 for items sourced from each. Second, `ACTIVE` certifications past expiry move to `EXPIRED`, firing the packet-item invalidation cascade of §3.7. Third, `CURRENT` completions past expiry move to `LAPSED` with the same cascade. Fourth, the posture of every affected nurse recomputes, firing the posture cascade of §3.5 wherever the posture flips. Fifth, privilege re-derivation runs for every affected nurse, appending `SWEEP` evaluations wherever the derived status or scope changed, and each affected nurse's posture recomputes once more — except that a nurse whose step-four flip already fired the posture cascade is not recomputed again within the same run, so a single sweep cannot oscillate her (§3.5). The sweep is idempotent: a second run at the same clock changes nothing. Its response summarizes the run as counts — `licenses_expired`, `certifications_expired`, `completions_lapsed`, `postures_changed`, `shifts_auto_cancelled`, `packets_voided`, and `privilege_evaluations_appended`.

### 3.10. Regulatory Survey Audits

A `ComplianceOfficer` opens an audit run with `window_start`, `window_end`, and `per_unit_sample_size`, the maximum number of nurses sampled per unit, at least 1 — a smaller value is `ERR_INVALID_REQUEST` (400). The window is inclusive at both ends; `window_start` must be strictly before `window_end`, and `window_end` must not lie after the current date — violations are `ERR_INVALID_DATE_RANGE`. The run is born `INITIATED`, with its creator recorded in `created_by_user_id`.

Beginning fieldwork moves the run from `INITIATED` to `FIELD_WORK` — from any other state, `ERR_INVALID_AUDIT_STATE` — and computes the deterministic sample stored in `sampled_nurse_ids`. Units are iterated in creation order. Within a unit, candidates are the nurses with at least one `COMPLETED` shift assignment in that unit whose start date falls inside the window, inclusive. Candidates rank by their completed-shift count in that unit, descending, with ties broken by the nurse's own `created_at`, ascending. The first `per_unit_sample_size` candidates of each unit are taken.

Issuing findings moves the run from `FIELD_WORK` to `FINDINGS_ISSUED` — again, any other state is `ERR_INVALID_AUDIT_STATE` — and evaluates each sampled nurse's credential slots as of `window_end`, purely from dates, regardless of sweep-driven statuses. The practice-authority slot is valid when the nurse holds a license with `expires_on` on or after `window_end` that is not `SURRENDERED`. The BLS slot is valid when she holds a `BLS` certification with `expires_on` on or after `window_end` that is not `REVOKED`. One further slot exists per mandatory competency requirement applicable to her employment type, valid when a completion for it has `expires_on` on or after `window_end`. Every deficient slot produces one `OPEN` audit finding — linked back through `audit_run_id` and `nurse_id` — with the matching `finding_type` of `LICENSE_NOT_CURRENT_IN_WINDOW`, `CERTIFICATION_NOT_CURRENT_IN_WINDOW`, or `COMPETENCY_NOT_CURRENT_IN_WINDOW`, and a `detail` naming the deficient slot: `practice_authority` for the practice-authority slot, `BLS` for the BLS slot, and the requirement `code` for a competency slot.

Two rates and a projection are computed and stored at this point; all three stay null until issue-findings. The `point_in_time_rate` pools all sampled nurses: one hundred times the number of valid slots divided by the total number of slots across every sampled nurse, rounded half up to 2 decimals — and 100.0 when there are no slots at all. The `shift_incidence_rate` looks instead at the sampled nurses' `COMPLETED` assignments whose start dates fall inside the window: one hundred times the number of those shifts stamped `was_clear_at_start`, divided by the total number of those shifts, rounded half up to 2 decimals — and 100.0, vacuous compliance, when no such shifts exist. A nurse whose BLS expired only after her shifts ran therefore scores below 100 on the first rate but not the second. The `projected_deficiency_count` generalizes the sample per contributing unit, processed in unit creation order: from the unit's candidate count, the number actually sampled (the smaller of `per_unit_sample_size` and the candidate count), and the number of sampled nurses with at least one deficient slot, the stratum projection is the deficient count divided by the sampled count, multiplied by the candidate count, rounded half up to 2 decimals first; the run's projection is then the sum of those rounded strata, itself rounded half up to a whole number. This order is normative — rounding strata to integers before summing, or summing unrounded fractions, yields different numbers. Units with zero candidates contribute nothing, and when no unit has candidates the projection is 0.

Closing a run moves it from `FINDINGS_ISSUED` to `CLOSED` — any other state is `ERR_INVALID_AUDIT_STATE` — and requires every finding of the run resolved in some way: a close attempted while any finding still stands `OPEN` is rejected with `ERR_AUDIT_FINDINGS_OPEN`. Findings themselves move from `OPEN` to the terminal states `REMEDIATED` or `ACCEPTED_RISK` through the remediate and accept-risk actions; a finding in any state other than `OPEN` rejects with `ERR_INVALID_FINDING_STATE`.

## 4. Endpoint Definitions

General status code rules: creating a new resource returns 201; operations that modify an existing resource — including every state-transition action — return 200; deleting a session booking returns 204 with no body. Path parameters — `nurseId`, `licenseId`, `psvId`, `certId`, `actionId`, `packetId`, `itemId`, `reqId`, `unitId`, `shiftId`, `sessionId`, `bookingId`, `completionId`, `evalId`, `runId`, and `findingId` — identify the target resource and are validated for existence left to right per §2.9. List endpoints accept the optional filters `status`, `credential_posture`, `employment_type`, `nurse_id`, `state_code`, `license_id`, `cert_type`, `target_unit_id`, `packet_id`, `requirement_id`, `session_booking_id`, `unit_id`, `session_id`, `completion_id`, `audit_run_id`, and `window_mode` where each is applicable to the listed resource, alongside the pagination parameters of §2.3; the expiry report additionally accepts `nurse_id`. A filter is applicable to a resource exactly when the resource carries a stored field of that name; applicable filters match by exact equality on the stored value, and query parameters naming inapplicable filters are ignored. The full request and response shape of every operation is reconstructed from the §3 narratives; this table fixes only the HTTP contract.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /credentialing/nurses | Create a nurse record, born `ONBOARDING` with posture `SCHEDULING_SUSPENDED` and privilege `NONE` | CredentialingSpecialist |
| GET | /credentialing/nurses | List nurses with filters and pagination | All roles |
| GET | /credentialing/nurses/{nurseId} | Get one nurse, including computed posture and privilege fields | All roles |
| PATCH | /credentialing/nurses/{nurseId} | Update the nurse profile including PSOR; OCC-guarded; increments the nurse version by 1 | CredentialingSpecialist |
| POST | /credentialing/nurses/{nurseId}/activate | Move `ONBOARDING` → `ACTIVE`; requires an `ACTIVE` license and the facility state in derived scope | CredentialingSpecialist |
| POST | /credentialing/nurses/{nurseId}/terminate | Move to `TERMINATED`; future shifts auto-cancel, non-terminal packets void, posture forced | CredentialingSpecialist |
| POST | /credentialing/state-licenses | Register a license (born `DRAFT`); the multistate flag requires a compact state code | CredentialingSpecialist |
| GET | /credentialing/state-licenses | List licenses, reverse-lookup by nurse | All roles |
| GET | /credentialing/state-licenses/{licenseId} | Get one license | All roles |
| POST | /credentialing/state-licenses/{licenseId}/submit | Move `DRAFT` → `PENDING_VERIFICATION` | CredentialingSpecialist |
| POST | /credentialing/state-licenses/{licenseId}/attest | Move `VERIFIED` → `ACTIVE`; segregated from the creator; requires a fresh verified PSV | PrimarySourceVerifier |
| POST | /credentialing/state-licenses/{licenseId}/renew | Renew `EXPIRED` → `ACTIVE` (or `ENCUMBERED` under an open license-scope adjudication); proactive `ACTIVE` renewal only within the 60-day window; requires a fresh verified PSV | CredentialingSpecialist |
| POST | /credentialing/state-licenses/{licenseId}/surrender | Any non-terminal status → `SURRENDERED` (terminal) | ComplianceOfficer |
| POST | /credentialing/primary-source-verifications | Request a PSV for a license in `PENDING_VERIFICATION`, `VERIFIED`, or `EXPIRED` | CredentialingSpecialist |
| GET | /credentialing/primary-source-verifications | List PSVs, reverse-lookup by license | All roles |
| GET | /credentialing/primary-source-verifications/{psvId} | Get one PSV | All roles |
| POST | /credentialing/primary-source-verifications/{psvId}/record-result | `REQUESTED` → `VERIFIED` / `DISCREPANCY` / `UNREACHABLE`; segregated from the requester; `VERIFIED` sets the 180-day freshness window and advances a pending license | PrimarySourceVerifier |
| POST | /credentialing/certifications | Record a certification (born `ACTIVE`) | CredentialingSpecialist |
| GET | /credentialing/certifications | List certifications, reverse-lookup by nurse | All roles |
| GET | /credentialing/certifications/{certId} | Get one certification | All roles |
| POST | /credentialing/certifications/{certId}/renew | `EXPIRED` → `ACTIVE` with a new expiry strictly after the current date | CredentialingSpecialist |
| POST | /credentialing/certifications/{certId}/revoke | `ACTIVE` or `EXPIRED` → `REVOKED` (terminal); invalidates sourced packet items | ComplianceOfficer |
| POST | /credentialing/disciplinary-actions | Report a disciplinary action (born `REPORTED`); nurse must be `ACTIVE`; license required exactly for license scope | ComplianceOfficer |
| GET | /credentialing/disciplinary-actions | List disciplinary actions, reverse-lookup by nurse or license | All roles |
| GET | /credentialing/disciplinary-actions/{actionId} | Get one disciplinary action | All roles |
| POST | /credentialing/disciplinary-actions/{actionId}/acknowledge | `REPORTED` → `UNDER_REVIEW` | ComplianceOfficer |
| POST | /credentialing/disciplinary-actions/{actionId}/adjudicate | `UNDER_REVIEW` → `ADJUDICATED` (sustained) or `DISMISSED`; segregated from the acknowledger; sustained fires the encumbrance cascade | ComplianceOfficer |
| POST | /credentialing/disciplinary-actions/{actionId}/resolve | `ADJUDICATED` → `RESOLVED` after the per-severity minimum active period; unwinds the encumbrance | ComplianceOfficer |
| POST | /credentialing/credential-packets | Create a packet (born `DRAFT`) and materialize its items from the base set plus target-unit requirements; at most one active packet per nurse | CredentialingSpecialist |
| GET | /credentialing/credential-packets | List packets, reverse-lookup by nurse or target unit | All roles |
| GET | /credentialing/credential-packets/{packetId} | Get one packet, including the computed readiness score | All roles |
| POST | /credentialing/credential-packets/{packetId}/submit | `DRAFT` → `SUBMITTED` by the owning nurse; all items must be submitted, verified, or waived | Nurse |
| POST | /credentialing/credential-packets/{packetId}/start-review | `SUBMITTED` → `UNDER_REVIEW`; segregated from the assembler | CredentialingSpecialist |
| POST | /credentialing/credential-packets/{packetId}/approve | `UNDER_REVIEW` → `APPROVED`; segregated from the assembler; all items verified or waived; nurse `ACTIVE` and `CLEAR` | CredentialingSpecialist |
| POST | /credentialing/credential-packets/{packetId}/reject | `UNDER_REVIEW` → `REJECTED`; segregated from the assembler; requires a reason | CredentialingSpecialist |
| POST | /credentialing/credential-packets/{packetId}/resubmit | `REJECTED` → `SUBMITTED` by the owning nurse; all items must be submitted, verified, or waived | Nurse |
| GET | /credentialing/packet-items | List packet items, reverse-lookup by packet | All roles |
| GET | /credentialing/packet-items/{itemId} | Get one packet item | All roles |
| POST | /credentialing/packet-items/{itemId}/submit-evidence | `MISSING` or `INVALIDATED` → `SUBMITTED` by the owning nurse; parent packet must be `DRAFT` or `REJECTED` | Nurse |
| POST | /credentialing/packet-items/{itemId}/verify | `SUBMITTED` → `VERIFIED`; server checks the underlying credential evidence and records the source row | CredentialingSpecialist |
| POST | /credentialing/packet-items/{itemId}/waive | `MISSING` or `SUBMITTED` → `WAIVED`; only non-critical items | CredentialingSpecialist |
| POST | /credentialing/competency-requirements | Create a competency or annual requirement (configuration) | ComplianceOfficer |
| GET | /credentialing/competency-requirements | List requirements | All roles |
| GET | /credentialing/competency-requirements/{reqId} | Get one requirement | All roles |
| POST | /credentialing/competency-completions | Record a completion (born `CURRENT`); supersedes prior rows for the same nurse and requirement; computes expiry per window mode; nurses record only their own | Nurse, CredentialingSpecialist |
| GET | /credentialing/competency-completions | List completions, reverse-lookup by nurse, requirement, or booking | All roles |
| GET | /credentialing/competency-completions/{completionId} | Get one completion | All roles |
| POST | /credentialing/units | Create a unit with its required certification types | NurseManager |
| GET | /credentialing/units | List units | All roles |
| GET | /credentialing/units/{unitId} | Get one unit, including computed staffing counters | All roles |
| POST | /credentialing/shift-assignments | Book a shift; gates in order: nurse `ACTIVE`, posture `CLEAR`, unit certification requirements, half-open overlap, temporal window, weekly 60-hour cap | NurseManager |
| GET | /credentialing/shift-assignments | List shift assignments, reverse-lookup by nurse or unit | All roles |
| GET | /credentialing/shift-assignments/{shiftId} | Get one shift assignment | All roles |
| POST | /credentialing/shift-assignments/{shiftId}/start | `SCHEDULED` → `IN_PROGRESS` inside the shift window; posture still `CLEAR`; stamps the clear-at-start flag | NurseManager |
| POST | /credentialing/shift-assignments/{shiftId}/complete | `IN_PROGRESS` → `COMPLETED`; releases unit staffing counters | NurseManager |
| POST | /credentialing/shift-assignments/{shiftId}/cancel | `SCHEDULED` → `CANCELLED` (manual); releases unit counters; recomputes posture | NurseManager |
| POST | /credentialing/competency-sessions | Create a competency session with a capacity | NurseManager |
| GET | /credentialing/competency-sessions | List sessions, reverse-lookup by requirement | All roles |
| GET | /credentialing/competency-sessions/{sessionId} | Get one session | All roles |
| POST | /credentialing/competency-sessions/{sessionId}/bookings | Book a nurse into a session; capacity-bound; duplicate nurse rejected | NurseManager |
| GET | /credentialing/session-bookings | List bookings, reverse-lookup by session, nurse, or completion | All roles |
| GET | /credentialing/session-bookings/{bookingId} | Get one booking | All roles |
| POST | /credentialing/session-bookings/{bookingId}/complete | Mark attendance after the session ends; creates the linked completion (source session) and recomputes posture | NurseManager |
| DELETE | /credentialing/session-bookings/{bookingId} | Delete a booking, freeing capacity; only while attendance is unmarked | NurseManager |
| POST | /credentialing/privilege-evaluations | Explicit multistate-privilege re-evaluation; OCC-guarded on the nurse version; always appends a manual evaluation row and increments the nurse version by 1 | CredentialingSpecialist |
| GET | /credentialing/privilege-evaluations | List evaluation events, reverse-lookup by nurse | All roles |
| GET | /credentialing/privilege-evaluations/{evalId} | Get one evaluation event | All roles |
| POST | /credentialing/audit-runs | Create an audit run (born `INITIATED`) over an inclusive date window | ComplianceOfficer |
| GET | /credentialing/audit-runs | List audit runs | All roles |
| GET | /credentialing/audit-runs/{runId} | Get one audit run, including computed rates and the projection | All roles |
| POST | /credentialing/audit-runs/{runId}/begin-fieldwork | `INITIATED` → `FIELD_WORK`; computes the deterministic per-unit sample | ComplianceOfficer |
| POST | /credentialing/audit-runs/{runId}/issue-findings | `FIELD_WORK` → `FINDINGS_ISSUED`; creates one open finding per deficient slot; computes both rates and the deficiency projection | ComplianceOfficer |
| POST | /credentialing/audit-runs/{runId}/close | `FINDINGS_ISSUED` → `CLOSED`; requires zero open findings | ComplianceOfficer |
| GET | /credentialing/audit-findings | List findings, reverse-lookup by run or nurse | All roles |
| GET | /credentialing/audit-findings/{findingId} | Get one finding | All roles |
| POST | /credentialing/audit-findings/{findingId}/remediate | `OPEN` → `REMEDIATED` | ComplianceOfficer |
| POST | /credentialing/audit-findings/{findingId}/accept-risk | `OPEN` → `ACCEPTED_RISK` | ComplianceOfficer |
| GET | /credentialing/monitoring/expiry-report | Computed read: expiry buckets per credential; date-driven and independent of sweep status | All roles |
| POST | /credentialing/_clock/set_current_utc | Set the test-driving logical clock; no entity mutations | SystemOperator |
| POST | /credentialing/_ops/expiry-sweep | Ops-run checkpoint applying all time-based transitions in pinned order; idempotent at a fixed clock | SystemOperator |

## 5. Error Code Catalogue

The trigger condition for each error is specified in §2 and §3; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_OWNERSHIP_VIOLATION | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_NURSE_NOT_FOUND | 404 |
| ERR_LICENSE_NOT_FOUND | 404 |
| ERR_UNIT_NOT_FOUND | 404 |
| ERR_REQUIREMENT_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_CROSS_NURSE_REFERENCE | 422 |
| ERR_REQUIREMENT_NOT_APPLICABLE | 422 |
| ERR_INVALID_LICENSE_STATE | 409 |
| ERR_INVALID_PSV_STATE | 409 |
| ERR_INVALID_CERTIFICATION_STATE | 409 |
| ERR_INVALID_DISCIPLINE_STATE | 409 |
| ERR_INVALID_PACKET_STATE | 409 |
| ERR_INVALID_ITEM_STATE | 409 |
| ERR_INVALID_SHIFT_STATE | 409 |
| ERR_INVALID_AUDIT_STATE | 409 |
| ERR_INVALID_FINDING_STATE | 409 |
| ERR_INVALID_NURSE_STATE | 409 |
| ERR_INVALID_BOOKING_STATE | 409 |
| ERR_NURSE_NOT_CLEAR | 409 |
| ERR_HIRE_REQUIREMENTS_UNMET | 409 |
| ERR_PSV_STALE | 422 |
| ERR_UNIT_CERT_REQUIREMENT_UNMET | 403 |
| ERR_MULTISTATE_NON_COMPACT_STATE | 422 |
| ERR_ITEM_EVIDENCE_INVALID | 422 |
| ERR_SHIFT_OVERLAP | 409 |
| ERR_SESSION_FULL | 409 |
| ERR_BOOKING_DUPLICATE | 409 |
| ERR_ACTIVE_PACKET_EXISTS | 409 |
| ERR_PACKET_ITEMS_INCOMPLETE | 409 |
| ERR_ITEM_NOT_WAIVABLE | 422 |
| ERR_AUDIT_FINDINGS_OPEN | 409 |
| ERR_DUPLICATE_RESOURCE | 409 |
| ERR_SHIFT_IN_PAST | 422 |
| ERR_SCHEDULING_HORIZON_EXCEEDED | 422 |
| ERR_SHIFT_NOT_STARTABLE | 422 |
| ERR_INVALID_DATE_RANGE | 422 |
| ERR_DISCIPLINE_EFFECTIVE_FUTURE | 422 |
| ERR_RESOLUTION_PREMATURE | 422 |
| ERR_RENEWAL_WINDOW_NOT_OPEN | 422 |
| ERR_SESSION_NOT_ENDED | 422 |
| ERR_WEEKLY_HOURS_EXCEEDED | 422 |
| ERR_STALE_VERSION | 412 |
