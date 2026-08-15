# Professional License Verification & Renewal API — Product Requirements Document

## 1. Introduction

Every employer in a licensed profession carries the same quiet exposure: a nurse whose RN lapsed last quarter, an engineer whose PE is under board suspension, a billing specialist who appears on a federal exclusion list — each renders the work they touch non-compliant, often retroactively. This document specifies an employer-side API for professional license verification and renewal. The system maintains an inventory of the credentials each employee holds against the requirements of their role, re-verifies every credential against its primary source on a fixed cadence, restricts work the moment a credential stops being trustworthy, tracks the continuing-education record that gates reinstatement, and pays for renewals through a controlled reimbursement pipeline with auditable money counters.

The API is organized around five constituencies with deliberately separated duties. A compliance administrator defines license-type policy and the multi-state role-requirement matrix; compliance officers record primary-source verifications, adjudicate continuing-education submissions, review reimbursement requests, and process board disciplinary feeds and exclusion-list screenings; HR partners own the employee roster and disburse approved reimbursements; employees act only on their own records; and external auditors assemble tamper-evident evidence packages over arbitrary reporting periods. All temporal behavior — expiration sweeps, overdue detection, education windows, screening validity, audit closure — hangs off a logical clock rather than wall-clock time, so compliance posture is deterministic and replayable. All endpoints are mounted under the `/licensing` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contract, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles: `ComplianceAdmin`, `ComplianceOfficer`, `HRPartner`, `Employee`, and `ExternalAuditor`. A request whose headers are missing or whose role is not one of these five is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400). A request whose role is well-formed but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting Employee; ownership checks on any resource that references an Employee compare the resource's foreign-key field to `X-User-ID` — most importantly, employee-scoped writes target a license, and the license's `employee_id` must equal the caller's `X-User-ID`. When `X-User-Role` is `ComplianceAdmin`, `ComplianceOfficer`, `HRPartner`, or `ExternalAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it (for example, as `verifier_user_id` on a verification event, `adjudicated_by_user_id` on an adjudicated CE activity or disciplinary event, `submitted_by_user_id`, `decided_by_user_id`, or `paid_by_user_id` on a renewal request, and `created_by_user_id` or `resolved_by_user_id` on an exclusion screening) but never compares it to any entity's `id`. Segregation-of-duties checks instead compare it against previously recorded operator identifiers, as described in §2.10.

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

---

### 2.3. Pagination

List endpoints are paginated through query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource — license types, role requirements, employees, licenses, CE activities, renewal requests, disciplinary events, exclusion screenings, and audit packages — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments by one on every mutation, including mutations driven by cascades such as the expiry sweep or a disciplinary confirmation.

The verification log is the sole exception. A VerificationEvent is an append-only record and carries only `id` and `created_at`; both `updated_at` and `version` are absent, since a log entry never changes once written.

### 2.5. The Logical Clock and Date Semantics

Compliance posture is computed against a logical clock, never against wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to the host's clock afterwards. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant (ISO 8601 UTC); the response echoes the new instant as `current_utc`. Every temporal rule in this document — the expiry sweep, verification-overdue detection, rolling CE windows, screening validity windows, audit-period closure, the `paid_on` stamp on a disbursement, the `sealed_at` stamp on an evidence package — reads this logical clock. Advancing the clock triggers the license expiry sweep described in §3.5. Where a rule speaks of "the logical current date", it means the calendar date (UTC) of the logical clock's current instant, and date arithmetic is in whole calendar days unless a rule states otherwise.

### 2.6. Nested Resource Retrieval

Several resources are addressed through another resource in the URL — a license's verification log, an employee's screenings, a license's renewal requests, and so on. Path identifiers are validated in strict left-to-right order, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, before any deeper validation runs. The same error covers body foreign keys on creation payloads: an `employee_id`, `license_type_id`, or `license_id` that references a non-existent resource fails with `ERR_NOT_FOUND`. Referenced-resource existence is always checked before field-domain validation, so a request with both a dangling foreign key and a malformed field surfaces the not-found error.

### 2.7. Optimistic Concurrency Control

Exactly one operation is guarded by optimistic concurrency control: the creation of a renewal reimbursement request against a license. That request body must carry `expected_license_version`, a non-optional field holding the `version` of the parent license as the client last observed it. If another writer has advanced the license's version since that read — by recording a verification, opening another renewal draft, or through a disciplinary or sweep cascade — the supplied value no longer matches the license's current `version`, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from filing a renewal against an expiry snapshot or computed state it has never seen. No other endpoint accepts a version field; every other mutation is governed purely by the validation cascade of §2.8.

### 2.8. Order of Validation

Every request is screened by a fixed cascade of checks, and the first failing check determines the error returned — earlier failures mask later ones. The order is:

1. **User context** — the `X-User-ID` and `X-User-Role` headers are present and name a declared role (`ERR_MISSING_OR_INVALID_USER_CONTEXT`).
2. **Role authorization** — the role is permitted for the endpoint, and an `Employee` actor owns the target license on employee-scoped writes (`ERR_UNAUTHORIZED_ROLE`).
3. **Path existence** — path identifiers resolve, validated left to right (`ERR_NOT_FOUND`).
4. **Referenced-resource existence** — body foreign keys such as `employee_id`, `license_type_id`, and `license_id` resolve (`ERR_NOT_FOUND`). This step always runs before field-domain validation.
5. **Field-domain** — required fields are present, types match, enums are in range, numeric ranges are honored, and sanity dates (`screened_on`, `effective_on`, `completed_on`) are not in the future (`ERR_INVALID_REQUEST`).
6. **State-machine from-state** — the target resource sits in a from-state of the requested transition: a request not in `DRAFT` or `MORE_INFO` cannot be submitted, an activity not `LOGGED` cannot be validated or rejected, an event not `RECEIVED` cannot be confirmed or dismissed, a screening not `UNDER_REVIEW` cannot be resolved, a package not `BUILDING` cannot be sealed, and a `REVOKED` license accepts no verification at all (`ERR_INVALID_STATE`).
7. **Safety gates** — renewal submission while the license is `SUSPENDED` (`ERR_LICENSE_SUSPENDED`), and license registration for an employee with a `CONFIRMED_MATCH` screening (`ERR_EMPLOYEE_SCREENING_FLAGGED`).
8. **Uniqueness** — case-insensitive employee email, the per-employee license triple, the requirement triple, the license-type code, and per-license board case numbers (`ERR_DUPLICATE_EMAIL`, `ERR_DUPLICATE_LICENSE`, `ERR_DUPLICATE_ROLE_REQUIREMENT`, `ERR_DUPLICATE_LICENSE_TYPE_CODE`, `ERR_DUPLICATE_CASE_NUMBER`).
9. **Segregation of duties** (`ERR_SOD_SAME_USER`).
10. **Stale-version guard** on renewal-request creation (`ERR_STALE_VERSION`).
11. **License validity dates** — first that `expires_on` falls after `issued_on` (`ERR_INVALID_DATES`), and only then that the validity window is within bounds (`ERR_VALIDITY_WINDOW_EXCEEDED`).
12. **Verification chronology** (`ERR_VERIFICATION_OUT_OF_ORDER`, `ERR_DUPLICATE_VERIFICATION`, `ERR_INVALID_VERIFICATION_DATE`).
13. **Audit-period shape and overlap** (`ERR_INVALID_AUDIT_PERIOD`, `ERR_AUDIT_PERIOD_OVERLAP`).
14. **Screening-window overlap** (`ERR_SCREENING_WINDOW_OVERLAP`).
15. **Referential gates** — the license must be renewable for a submit (`ERR_LICENSE_NOT_RENEWABLE`), CE-eligible for an activity (`ERR_LICENSE_NOT_CE_ELIGIBLE`), and CE-sufficient for reinstatement (`ERR_CE_HOURS_INSUFFICIENT`).
16. **Fiscal ceilings** — the per-request hard claim cap first (`ERR_CLAIM_EXCEEDS_HARD_CAP`), then the employer committed cap (`ERR_COMMITTED_CAP_EXCEEDED`).

### 2.9. Precision, Rounding, and Monetary Values

All monetary values are integer cents, end to end: `claimed_amount_cents`, `estimated_reimbursable_cents`, `approved_amount_cents`, the reimbursement tier ceilings, the hard claim cap, and both employee money counters are whole numbers of cents. CE hours and progress percentages are carried to two decimal places; wherever rounding is required it is round half up. Two rounding orderings are contractual: per-activity hour rounding happens at activity creation, before any summation (§3.4); and the half-value term of the receipt-based reimbursement estimate rounds half up to a whole cent when the term is odd (§3.6).

### 2.10. Segregation of Duties

Three adjudication pairs enforce segregation of duties, each rejecting a same-operator decision with `ERR_SOD_SAME_USER` (HTTP 403). The officer who approves or rejects a renewal request must differ from its `submitted_by_user_id`. The officer who confirms, dismisses, or resolves a disciplinary event must differ from its `created_by_user_id`. The officer who confirms or clears an exclusion screening must differ from its `created_by_user_id`. Because operator identifiers for these roles are opaque (§2.1), the comparison is always against the identifier recorded on the resource at intake, never against a roster entity.

## 3. Business Logic & Workflows

### 3.1. License-Type Policy and the Role-Requirement Matrix

Policy begins with the license type. A `ComplianceAdmin` registers each credential family the company tracks — an RN, a PE, a CPA — under a unique program `code` and a human-readable `name`; a second type reusing an existing code is rejected with `ERR_DUPLICATE_LICENSE_TYPE_CODE`. The type carries its continuing-education policy in two fields: `ce_hours_required_per_cycle`, a non-negative number of hours required per renewal cycle where a value of zero disables the CE gate entirely, and `cycle_length_months`, the renewal-cycle length used for the cycle CE window, between 1 and 120 months inclusive. Its verification cadence lives in `verification_frequency_days`, the primary-source re-verification interval, between 1 and 3650 days inclusive. Its lapse policy lives in `grace_period_days`, a non-negative count of days after expiration before an expired credential is treated as lapsed (§3.5).

Reimbursement policy is also anchored on the type. The `reimbursement_mode` selects one of two estimate variants — `RECEIPT_BASED` or `FLAT_SCHEDULE` — and three amounts parameterize them: `reimburse_full_up_to_cents` sets the ceiling of the fully reimbursed band, `reimburse_half_up_to_cents` sets the ceiling of the half-reimbursed band and must be at least the full-band ceiling, and `flat_schedule_amount_cents` is the fixed flat-mode reimbursement, recorded as zero when the mode is receipt-based. Independent of mode, `hard_claim_cap_cents` is a strictly positive absolute ceiling: any request claiming more than it is rejected outright (§3.6). Finally, `requires_exclusion_screening` marks types whose holders work in regulated roles and therefore need exclusion-list screening (§3.8).

Which credentials an employee must hold is expressed as a matrix of role requirements, maintained by the `ComplianceAdmin`. Each row binds a `role_code` to a `license_type_id` and a two-letter `state_code` — one row per state for multi-state licensure — and `is_required` declares whether that combination is mandatory. The triple of role, type, and state is unique per matrix; a conflicting insert fails with `ERR_DUPLICATE_ROLE_REQUIREMENT`. Requirement maintenance has immediate workforce consequences: creating a row re-derives the work authorization of every employee carrying that `role_code`, so a new mandatory row can engage `MISSING_LICENSE` across the roster the moment it exists, and deleting a row re-derives again, potentially clearing that reason. The matrix can be listed with `role_code`, `state_code`, or `license_type_id` filters.

### 3.2. The Employee Roster and the Work-Authorization Derivation

An `HRPartner` onboards each employee with a `full_name`, a `work_email` that is unique case-insensitively (a second registration differing only in letter case fails with `ERR_DUPLICATE_EMAIL`), and a `role_code` that ties the employee to the requirement matrix. Onboarding computes compliance posture immediately: `screening_posture` starts `CLEAR`, both money counters — `reimbursement_committed_cents` and `reimbursement_paid_cents` — start at zero, and `work_authorization` is derived from the matrix, so an employee whose role mandates a license they do not yet hold enters the roster already `RESTRICTED` with reason `MISSING_LICENSE`, while an employee with no unmet mandatory rows enters `AUTHORIZED`. Later profile updates to `full_name`, `work_email`, or `role_code` are applied by the `HRPartner`; a change to `role_code` re-runs the derivation against the new role's mandatory rows and may engage `MISSING_LICENSE` on the spot. The roster can be listed with `role_code`, `work_authorization`, or `screening_posture` filters, and a single employee read returns the full computed posture.

Work authorization is a computed verdict over the employee's mandatory matrix rows — the rows with `is_required` set that match the employee's `role_code`. Five reasons can restrict an employee, and when several apply at once the highest-precedence one surfaces in `restriction_reason` while the rest remain latent. In precedence order from highest to lowest: `SCREENING_FLAGGED` applies when the employee's `screening_posture` is `FLAGGED`; `LICENSE_SUSPENDED` applies when any mandatory row is covered by a license in `SUSPENDED`; `LICENSE_LAPSED` applies when any mandatory row is covered by a license in `LAPSED` or `REVOKED`; `VERIFICATION_OVERDUE` applies when any mandatory row is covered by an `ACTIVE` license whose `verification_posture` is `OVERDUE`; and `MISSING_LICENSE` applies when a mandatory row has no license row at all, or every matching license is still `PENDING_VERIFICATION`. When any reason applies, `work_authorization` is `RESTRICTED` and the employee must not perform licensed work; otherwise it is `AUTHORIZED` and `restriction_reason` is null. Notably, an `EXPIRED` license still inside its grace period is deliberately not a restriction reason. The `screening_posture` input to this derivation is itself computed from the employee's screening records: `FLAGGED` when any screening stands at `CONFIRMED_MATCH`, otherwise `PENDING_REVIEW` when any stands at `UNDER_REVIEW`, otherwise `CLEAR`.

Two counters track each employee's fiscal exposure through the reimbursement pipeline. `reimbursement_committed_cents` is the open pipeline: the sum of claimed amounts over the employee's requests currently in `SUBMITTED` or `MORE_INFO`, plus the sum of approved amounts over requests currently in `APPROVED`. `reimbursement_paid_cents` is the lifetime sum of approved amounts over the employee's `PAID` requests. Every pipeline transition in §3.6 adjusts these counters in step, so they can be trusted without re-walking request history.

### 3.3. Registering Licenses and Running Primary-Source Verification

A `ComplianceOfficer` registers each credential into the inventory with the holder's `employee_id`, the `license_type_id`, the issuing `state_code` (multi-state licensure means one license row per state), the board-issued `license_number`, and the `issued_on` and `expires_on` dates. Two date rules guard creation, evaluated in this order so the simpler defect surfaces first: `expires_on` must fall strictly after `issued_on` (`ERR_INVALID_DATES`), and only then is the validity window checked — `expires_on` may not exceed `issued_on` by more than 730 days (`ERR_VALIDITY_WINDOW_EXCEEDED`). Uniqueness is per holder, type, and state: a second license for the same triple fails with `ERR_DUPLICATE_LICENSE`. One hard safety gate sits ahead of everything else at registration — an employee with any screening standing at `CONFIRMED_MATCH` may not have new licenses registered at all, and the attempt is refused with `ERR_EMPLOYEE_SCREENING_FLAGGED`.

A freshly registered license enters at `PENDING_VERIFICATION` with `verification_posture` of `NEVER_VERIFIED`, `last_verified_on` null, both CE tallies at zero, and `ce_cycle_anchor_on` set to `issued_on`; its `alert_tier` is computed immediately. Registration also re-derives the holder's work authorization, but with a deliberate asymmetry: a `PENDING_VERIFICATION` row does not satisfy a mandatory matrix row, so `MISSING_LICENSE` persists until the first successful verification. The inventory supports listing with `employee_id`, `license_type_id`, `state_code`, `status`, `verification_posture`, or `alert_tier` filters, plus a per-employee listing of everything one holder carries.

Primary-source verification is the cadence that keeps the inventory trustworthy, and it is a `ComplianceOfficer` duty. Recording a verification takes the `verified_on` date the primary source was contacted, the `source` channel — `STATE_BOARD_API`, `MANUAL_UPLOAD`, or `NURSYS` — and the `outcome`, one of `VERIFIED`, `MISMATCH`, or `UNREACHABLE`; the request may optionally pin `next_verification_due_on` to override the computed due date. Chronology rules protect the log's integrity: a `verified_on` more than one day ahead of the logical current date is invalid (`ERR_INVALID_VERIFICATION_DATE`); on a license that has been verified before, `verified_on` must be strictly after `last_verified_on` (`ERR_VERIFICATION_OUT_OF_ORDER`); and any repeat of a date already present in the license's log is a duplicate (`ERR_DUPLICATE_VERIFICATION`) — which is why a same-day re-verification surfaces as a duplicate rather than as out-of-order. Attempting to verify a license in `SUSPENDED` or `REVOKED` has no originating transition and fails with `ERR_INVALID_STATE`.

What an event does depends on where the license stands. On a `PENDING_VERIFICATION` license, a `VERIFIED` outcome promotes the license to `ACTIVE` and stamps `last_verified_on` — but a pending license that has already expired cannot be verified, so an `expires_on` earlier than `verified_on` is rejected with `ERR_INVALID_VERIFICATION_DATE`. A `MISMATCH` or `UNREACHABLE` outcome on a pending license changes nothing but the log: the license stays `PENDING_VERIFICATION`, its posture stays `NEVER_VERIFIED`, and only its `alert_tier` is recomputed. On an `ACTIVE` license, a `VERIFIED` event is renewal-in-place or cadence re-verification: `last_verified_on` advances, and `expires_on` extends to the later of its current value and `verified_on` plus 365 days. On an `EXPIRED` or `LAPSED` license, a `VERIFIED` event is reinstatement: the license returns to `ACTIVE`, `expires_on` becomes `verified_on` plus 365 days, and `ce_cycle_anchor_on` is re-set to `verified_on` so the cycle CE window restarts from the new anchor — but reinstatement runs only after the CE gate of §3.4 passes. In every successful case, `next_verification_due_on` defaults to the earlier of `verified_on` plus the type's `verification_frequency_days` and the (possibly extended) `expires_on`, unless the request pinned it; `verification_posture` becomes `CURRENT`; `alert_tier` is recomputed; and the holder's work authorization is re-derived, which can clear `MISSING_LICENSE` on a first verification, `VERIFICATION_OVERDUE` on a cadence verification, or `LICENSE_LAPSED` on a reinstatement.

Every recorded event is appended to the license's verification log — an append-only sequence capturing `license_id`, `verified_on`, `source`, `outcome`, the recording officer's `verifier_user_id`, and the `next_verification_due_on` in effect after the event. Recording a verification increments the license's `version` by one, which is precisely what the renewal-creation guard of §2.7 keys on. The `verification_posture` itself reads `NEVER_VERIFIED` while `last_verified_on` is null, `OVERDUE` once the logical current date is strictly after `next_verification_due_on` — a current date exactly equal to the due date still reads `CURRENT` — and `CURRENT` otherwise. And because a verification is new evidence, any `SEALED` audit package whose period contains the event's `verified_on` is invalidated as described in §3.9.

### 3.4. Continuing Education: Logging, Half-Hour Rounding, and the Two Progress Windows

Continuing-education credit is logged per license, either by the holder — an `Employee` acting on their own license — or by a `ComplianceOfficer`. Each activity records the `provider_name`, an `activity_title`, the raw reported `hours` (at least a quarter hour and no more than two hundred), and a `completed_on` date that may not lie after the logical current date (`ERR_INVALID_REQUEST`). Accrual only makes sense against a live credential, so the host license must stand in `ACTIVE`, `EXPIRED`, `LAPSED`, or `SUSPENDED`; logging against a `PENDING_VERIFICATION` or `REVOKED` license fails with `ERR_LICENSE_NOT_CE_ELIGIBLE`. At creation the system computes `rounded_hours`: the raw hours are rounded half up to the nearest half hour, per activity, before any summation ever happens. The ordering is contractual — two activities of 0.74 hours each round to 0.5 apiece and therefore tally 1.0, never 1.5. A new activity lands in `LOGGED` and contributes to no tally until adjudicated.

Adjudication belongs to a `ComplianceOfficer`. Validating a logged activity moves it to `VALIDATED` and recomputes the host license's tallies and progress percentages; rejecting one moves it to `REJECTED` and leaves every tally untouched. Either way, `adjudicated_by_user_id` records who decided — it stays null while the activity is `LOGGED` — and both outcomes are terminal, so adjudicating an activity that is no longer `LOGGED` fails with `ERR_INVALID_STATE`. Activities can be listed per license with a `status` filter.

Two windows frame a license's tallies, and both sum `rounded_hours` over the license's `VALIDATED` activities only. `cycle_ce_hours_validated` covers the cycle window: from `ce_cycle_anchor_on` through the earlier of the anchor plus the type's `cycle_length_months` months and the license's `expires_on`, inclusive at both ends; because reinstatement re-anchors the cycle (§3.3), the tally restarts with it. `rolling_ce_hours_validated` covers the regulator's window: the 365-day span ending on the logical current date — from 364 days before it through the current date itself, inclusive at both ends. From these sums come two progress percentages, each rounded half up to two decimal places and each null when the type's `ce_hours_required_per_cycle` is zero. `ce_progress_reported_pct` is the employer-reported posture — what the current cycle's file shows — computed from the cycle tally against the requirement. `ce_progress_required_pct` is the regulator-required posture — what the rolling 365-day file shows — computed from the rolling tally against the same requirement. Identical inputs can legitimately produce two different percentages, and both are exposed on every license read.

The cycle tally doubles as the reinstatement gate. When a license type requires any continuing education at all, verifying an `EXPIRED` or `LAPSED` license back to `ACTIVE` demands a `cycle_ce_hours_validated` of at least the type's `ce_hours_required_per_cycle`; a shortfall blocks the reinstatement with `ERR_CE_HOURS_INSUFFICIENT`. Types with a zero requirement impose no gate.

### 3.5. Expiration Alerting and the Clock-Driven Lapse Sweep

Every license carries an `alert_tier` measuring its distance from expiration. For a license in `PENDING_VERIFICATION` or `ACTIVE`, count the whole days from the logical current date to `expires_on`: ninety-one or more days out reads `NONE`; sixty-one through ninety days reads `T90`; thirty-one through sixty reads `T60`; one through thirty reads `T30`; and zero — expiration day itself — or any negative distance reads `AT_EXPIRY`. Boundaries fall into the nearer tier, so exactly ninety days is `T90`, exactly sixty is `T60`, and exactly thirty is `T30`. A license in any other status — `EXPIRED`, `LAPSED`, `SUSPENDED`, or `REVOKED` — carries `AT_EXPIRY` regardless of the calendar.

Advancing the logical clock runs the expiry sweep. Licenses are processed in ascending `expires_on` order, ties broken by ascending `created_at`. An `ACTIVE` license whose `expires_on` now falls strictly before the current date drops to `EXPIRED` and takes `alert_tier` of `AT_EXPIRY`. An `EXPIRED` license whose grace has fully run out — the current date strictly after `expires_on` plus the type's `grace_period_days` — drops to `LAPSED`, again at `AT_EXPIRY`. After the transitions, the sweep refreshes `verification_posture` and `alert_tier` for every license still in `PENDING_VERIFICATION` or `ACTIVE`, and re-derives work authorization for every affected holder; each such mutation refreshes the entity's `updated_at` and increments its `version`. Two nuances matter downstream. An `EXPIRED` license still inside its grace period is not, by itself, a restriction reason — the holder keeps working while renewal is arranged. But the moment the license reaches `LAPSED` (or `REVOKED`), the `LICENSE_LAPSED` reason engages for every mandatory matrix row the license covers.

### 3.6. Renewal Reimbursement: Estimates, Caps, and the Review Pipeline

An employee — acting on their own license — or a `ComplianceOfficer` opens a renewal reimbursement request by supplying the `claimed_amount_cents` from the renewal receipt together with the OCC guard `expected_license_version` described in §2.7. The claim must be non-negative, and it may not exceed the license type's `hard_claim_cap_cents`; a claim above that absolute ceiling is rejected outright with `ERR_CLAIM_EXCEEDS_HARD_CAP`. On acceptance the request is born `DRAFT`: the system snapshots the license's current `expires_on` into `expires_on_at_create` so later expiry movement cannot silently re-scope the request, computes `estimated_reimbursable_cents` once and for all, and — because the license now carries a dependent draft — increments the license's `version` by one. A draft commits no money. Requests can be listed per license with a `status` filter or fetched individually.

The estimate depends on the type's `reimbursement_mode`. Under `RECEIPT_BASED`, the claim is reimbursed in marginal bands: the band up to `reimburse_full_up_to_cents` counts in full, the band above it up to `reimburse_half_up_to_cents` counts at half its value — and when that half band works out to an odd number of cents, the half rounds half up to a whole cent — while anything beyond the half ceiling counts for nothing; the estimate is then the smaller of the claim and that tiered total. Under `FLAT_SCHEDULE`, the estimate is simply the smaller of `flat_schedule_amount_cents` and the claim, so the same receipt yields a different estimate under the two modes. The estimate is fixed at creation and never recomputed, even if policy changes later.

Submitting moves a request from `DRAFT` to `SUBMITTED`, or resubmits it from `MORE_INFO` back to `SUBMITTED`; a request in any other state fails with `ERR_INVALID_STATE`. When the actor is an `Employee`, the license must be their own (`ERR_UNAUTHORIZED_ROLE`). Two license-state gates then apply in this order: a `SUSPENDED` license blocks submission with `ERR_LICENSE_SUSPENDED`, and a license outside `ACTIVE`, `EXPIRED`, or `LAPSED` fails with `ERR_LICENSE_NOT_RENEWABLE`. Last comes the fiscal gate: the employer caps each employee's open commitment at one million cents — ten thousand dollars — so a first submission whose claim would push `reimbursement_committed_cents` over that ceiling fails with `ERR_COMMITTED_CAP_EXCEEDED` (HTTP 402). A successful submission stamps `submitted_by_user_id` with the actor and, on a first submission from `DRAFT`, adds the full `claimed_amount_cents` to the committed counter. Resubmission from `MORE_INFO` leaves the counter untouched — the claim was committed when first sent — so the cap is re-evaluated but cannot newly fail.

Review is a `ComplianceOfficer` function under segregation of duties: whoever submitted a request may not decide it, and a deciding officer whose `X-User-ID` equals `submitted_by_user_id` is turned away with `ERR_SOD_SAME_USER`. Three outcomes are possible from `SUBMITTED`. An officer needing clarification sends the request back to `MORE_INFO` with an `info_note`, leaving the committed counter unchanged. Approval fixes `approved_amount_cents` at the smaller of `estimated_reimbursable_cents` and the remaining paid-cap headroom — the employer's one-million-cent paid ceiling minus the employee's lifetime `reimbursement_paid_cents` — records `decided_by_user_id`, and trims the committed counter by the disallowed delta, the claim minus the approved amount; whatever overflows the paid cap is dropped outright, not deferred to a later cycle. Rejection records the `decision_note`, moves the request to `REJECTED`, and releases the entire claim from the committed counter. Approving or rejecting a request that is not `SUBMITTED` fails with `ERR_INVALID_STATE`.

Disbursement belongs to the `HRPartner`. Marking an `APPROVED` request paid moves it to `PAID`, sets `paid_on` — which stays null until this moment — to the logical current date, records `paid_by_user_id` and the `payment_ref`, moves the approved amount out of the committed counter, and adds it to `reimbursement_paid_cents`. Because a payment is audit-relevant evidence, any `SEALED` audit package whose period contains that `paid_on` is invalidated (§3.9). Administrative cleanup is the `ComplianceAdmin`'s: voiding is permitted from `DRAFT`, `SUBMITTED`, `MORE_INFO`, or `APPROVED` — anything else fails with `ERR_INVALID_STATE` — records a `void_reason`, and releases exactly what the request was still committing: nothing from a `DRAFT`, the full claim from `SUBMITTED` or `MORE_INFO`, and the approved amount from `APPROVED`. `PAID`, `REJECTED`, and `VOIDED` are terminal.

### 3.7. Disciplinary Action Monitoring and License Sanctions

Board actions arrive through two channels — `received_via` is `BOARD_FEED` or `MANUAL` — and a `ComplianceOfficer` records each event against a license with its `board_case_number`, an `event_type` of `WARNING`, `REPRIMAND`, `FINE`, `SUSPENSION`, or `REVOCATION`, and an `effective_on` date that may not lie after the logical current date (`ERR_INVALID_REQUEST`). Case numbers are unique per license: a second event repeating an existing `board_case_number` on the same license fails with `ERR_DUPLICATE_CASE_NUMBER`. The recorder's identity lands in `created_by_user_id`, and the event opens at `RECEIVED`. Normally a recorded event is inert until adjudicated — but when `confirm_at_creation` is set on a `SUSPENSION`, the sanction bites immediately: an `ACTIVE` license drops to `SUSPENDED` at creation, `applied_at_creation` records that the effect was applied early, the event itself still sits at `RECEIVED` awaiting adjudication, and a later dismissal will unwind that suspension. Because a board action is evidence, recording one invalidates any `SEALED` audit package of the holder whose period contains `effective_on`.

Adjudication must come from a different officer than the recorder (`ERR_SOD_SAME_USER`), and each event can be listed per license with `status` and `event_type` filters. Confirming a `RECEIVED` event moves it to `CONFIRMED`, stamps `adjudicated_by_user_id`, and applies the sanction by type: a `SUSPENSION` whose effect was not already applied at creation moves an `ACTIVE` license to `SUSPENDED`; a `REVOCATION` moves a license in `ACTIVE` or `SUSPENDED` to `REVOKED`, which is terminal; `WARNING`, `REPRIMAND`, and `FINE` are recorded for the file and leave the license untouched. Dismissing a `RECEIVED` event moves it to `DISMISSED` with a `resolution_note`, and where the suspension had been applied at creation, dismissal compensates by returning the license from `SUSPENDED` to `ACTIVE`. Resolving a `CONFIRMED` event moves it to `RESOLVED` with a `resolution_note`; a resolved `SUSPENSION` lifts — the license returns from `SUSPENDED` to `ACTIVE` — only when no other open suspension still covers that license, where open means another `SUSPENSION` event either standing at `CONFIRMED` or still at `RECEIVED` with `applied_at_creation` set, while a `REVOCATION` never lifts. Every transition that suspends or revokes forces the license's `alert_tier` to `AT_EXPIRY` and re-derives the holder's work authorization: suspension engages the `LICENSE_SUSPENDED` reason, and revocation feeds the `LICENSE_LAPSED` bucket, since a revoked credential is as absent as a lapsed one for compliance purposes.

### 3.8. Exclusion-List Screening for Regulated Roles

Regulated roles demand screening against exclusion lists, and a `ComplianceOfficer` records each screening for an employee with the `list_source` — one of `OIG_LEIE`, `SAM_GSA`, or `STATE_MEDICAID` — a `screened_on` date that may not be future-dated (`ERR_INVALID_REQUEST`), and an `outcome` of `CLEAR` or `FLAGGED`. The two outcomes diverge at creation. A clear screen lands directly in `CLOSED_CLEAR` with `valid_until` set to `screened_on` plus thirty days — only `CLOSED_CLEAR` screenings ever carry a `valid_until` — and its validity window runs from `screened_on` through `valid_until`, inclusive at both ends. Clear windows cannot stack for the same employee and list: when an existing `CLOSED_CLEAR` screening for the same `employee_id` and `list_source` has a window containing the new `screened_on`, creation fails with `ERR_SCREENING_WINDOW_OVERLAP`. A flagged screen instead lands in `UNDER_REVIEW`, and — unless the employee's posture is already `FLAGGED` — pushes `screening_posture` to `PENDING_REVIEW`. Either creation re-derives the employee's work authorization, and either one invalidates any `SEALED` audit package of the employee whose period contains `screened_on`.

Resolving an `UNDER_REVIEW` screening is, again, someone else's job than the screener's (`ERR_SOD_SAME_USER`), and a screening in any other state rejects the attempt with `ERR_INVALID_STATE`. Confirming the match moves the screening to `CONFIRMED_MATCH`, records `resolved_by_user_id`, flips the employee's `screening_posture` to `FLAGGED`, and re-derives authorization — `SCREENING_FLAGGED` outranks every other restriction reason, and it also bars any new license registration for the employee per §3.3. Clearing a false positive moves the screening to `CLEARED_FALSE_POSITIVE` with a `resolution_note` and `resolved_by_user_id`, then recomputes the posture: `CLEAR` when no other `UNDER_REVIEW` or `CONFIRMED_MATCH` screening remains for the employee, and otherwise whatever those remaining records imply. `CLOSED_CLEAR`, `CONFIRMED_MATCH`, and `CLEARED_FALSE_POSITIVE` are all terminal, and screenings can be listed per employee with `status` and `list_source` filters.

### 3.9. Audit Evidence Packages and the Compliance Summary

An `ExternalAuditor` assembles evidence by opening an audit package for one employee over a half-open reporting period: `period_start` is inclusive, `period_end` is exclusive, and the end must fall strictly after the start (`ERR_INVALID_AUDIT_PERIOD`). Periods for the same employee may touch but may not intersect — a new package whose half-open period overlaps any `BUILDING` or `SEALED` package of the same employee fails with `ERR_AUDIT_PERIOD_OVERLAP`; strictly adjacent periods are allowed, and `INVALIDATED` packages no longer block anything. A new package opens at `BUILDING` with `evidence_item_count` at zero, and packages can be listed per employee with a `status` filter or fetched individually.

Sealing freezes the record, and only the `ExternalAuditor` may do it. The period must already be closed — `period_end` on or before the logical current date, otherwise `ERR_AUDIT_PERIOD_NOT_CLOSED` — and a package not in `BUILDING` cannot be sealed (`ERR_INVALID_STATE`). On sealing, `sealed_at` — null while the package is being built — takes the current logical timestamp and the `evidence_snapshot` is frozen: for the subject employee, every verification event whose `verified_on` falls in the period, every disciplinary event whose `effective_on` falls in it, every screening whose `screened_on` falls in it, and every `PAID` renewal request whose `paid_on` falls in it. Each snapshot item carries its `kind`, the referenced record's `ref_id`, and its `occurred_on`; items are ordered by `occurred_on` ascending, ties broken by `kind` in alphabetical order, then by the referenced record's `created_at` ascending. `evidence_item_count` is set to the snapshot's length.

A sealed package is brittle by design. If any dependent fact lands inside its sealed period — a verification recorded with a `verified_on` in the period, a disciplinary event with an `effective_on` in it, a screening with a `screened_on` in it, or a renewal request paid with a `paid_on` in it — the package flips from `SEALED` to `INVALIDATED`, the terminal state, with its snapshot retained for forensics; the auditor's remedy is to build and seal a fresh package. Separately from packages, a compliance-summary capability gives `ComplianceAdmin`, `ComplianceOfficer`, `HRPartner`, and `ExternalAuditor` callers — but not employees — a live posture readout: `authorized_employee_count`, `restricted_employee_count`, `flagged_employee_count`, `expired_license_count`, `overdue_verification_count`, `open_screening_count`, `committed_reimbursement_cents`, and `paid_reimbursement_cents`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — state transitions, verifications, adjudications, seals, and profile updates — return a `200 OK` status code. Deleting a role requirement returns `204 No Content`. The logical-clock capability returns `200 OK`. Readers must refer back to §3 narratives for request bodies, computed fields, and side effects; this table is only the address map.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/licensing/license-types` | Create a license type (renewal policy, CE policy, reimbursement policy) | ComplianceAdmin |
| GET    | `/licensing/license-types` | List license types | All roles |
| GET    | `/licensing/license-types/{id}` | Get one license type | All roles |
| POST   | `/licensing/role-requirements` | Create a role requirement (multi-state licensure matrix row) | ComplianceAdmin |
| GET    | `/licensing/role-requirements` | List role requirements with optional filters | All roles |
| GET    | `/licensing/role-requirements/{id}` | Get one role requirement | All roles |
| DELETE | `/licensing/role-requirements/{id}` | Delete a role requirement | ComplianceAdmin |
| POST   | `/licensing/employees` | Create an employee | HRPartner |
| GET    | `/licensing/employees` | List employees with optional filters | All roles |
| GET    | `/licensing/employees/{id}` | Get one employee (computed restriction and reimbursement fields) | All roles |
| PATCH  | `/licensing/employees/{id}` | Update employee profile; role_code change re-derives work authorization | HRPartner |
| POST   | `/licensing/licenses` | Register a license into the inventory | ComplianceOfficer |
| GET    | `/licensing/licenses` | List licenses with filters | All roles |
| GET    | `/licensing/licenses/{id}` | Get one license (computed posture, alert tier, CE tallies) | All roles |
| GET    | `/licensing/employees/{id}/licenses` | List licenses of one employee | All roles |
| POST   | `/licensing/licenses/{id}/verify` | Record a primary-source verification (initial, cadence, renewal-in-place, or reinstatement) | ComplianceOfficer |
| GET    | `/licensing/licenses/{id}/verification-events` | List the append-only verification log of a license | All roles |
| POST   | `/licensing/licenses/{id}/ce-activities` | Log a CE activity (license holder or officer) | Employee, ComplianceOfficer |
| GET    | `/licensing/licenses/{id}/ce-activities` | List CE activities of a license | All roles |
| POST   | `/licensing/ce-activities/{id}/validate` | Validate a logged CE activity (accrues to tallies) | ComplianceOfficer |
| POST   | `/licensing/ce-activities/{id}/reject` | Reject a logged CE activity | ComplianceOfficer |
| POST   | `/licensing/licenses/{id}/renewal-requests` | Create a renewal reimbursement request (OCC-guarded on the license version) | Employee, ComplianceOfficer |
| GET    | `/licensing/licenses/{id}/renewal-requests` | List renewal requests of a license | All roles |
| GET    | `/licensing/renewal-requests/{id}` | Get one renewal request | All roles |
| POST   | `/licensing/renewal-requests/{id}/submit` | Submit (or resubmit from MORE_INFO) a renewal request | Employee, ComplianceOfficer |
| POST   | `/licensing/renewal-requests/{id}/request-info` | Send a submitted request back for more information | ComplianceOfficer |
| POST   | `/licensing/renewal-requests/{id}/approve` | Approve a submitted request (SoD: approver differs from submitter) | ComplianceOfficer |
| POST   | `/licensing/renewal-requests/{id}/reject` | Reject a submitted request (SoD applies) | ComplianceOfficer |
| POST   | `/licensing/renewal-requests/{id}/mark-paid` | Mark an approved request paid | HRPartner |
| POST   | `/licensing/renewal-requests/{id}/void` | Administratively void a non-terminal request | ComplianceAdmin |
| POST   | `/licensing/licenses/{id}/disciplinary-events` | Record a board disciplinary event (feed or manual entry) | ComplianceOfficer |
| GET    | `/licensing/licenses/{id}/disciplinary-events` | List disciplinary events of a license | All roles |
| POST   | `/licensing/disciplinary-events/{id}/confirm` | Confirm a received event (SoD: confirmer differs from recorder); applies license effects | ComplianceOfficer |
| POST   | `/licensing/disciplinary-events/{id}/dismiss` | Dismiss a received event (SoD applies); reverts creation-applied suspensions | ComplianceOfficer |
| POST   | `/licensing/disciplinary-events/{id}/resolve` | Resolve a confirmed event (SoD applies) | ComplianceOfficer |
| POST   | `/licensing/employees/{id}/exclusion-screenings` | Record an exclusion-list screening | ComplianceOfficer |
| GET    | `/licensing/employees/{id}/exclusion-screenings` | List screenings of an employee | All roles |
| POST   | `/licensing/exclusion-screenings/{id}/confirm-match` | Confirm an UNDER_REVIEW screening as a true match (SoD applies) | ComplianceOfficer |
| POST   | `/licensing/exclusion-screenings/{id}/clear-false-positive` | Clear an UNDER_REVIEW screening as false positive (SoD applies) | ComplianceOfficer |
| POST   | `/licensing/employees/{id}/audit-packages` | Open an audit evidence package for an employee over a half-open period | ExternalAuditor |
| GET    | `/licensing/employees/{id}/audit-packages` | List audit packages of an employee | All roles |
| GET    | `/licensing/audit-packages/{id}` | Get one audit package | All roles |
| POST   | `/licensing/audit-packages/{id}/seal` | Seal a closed package; freezes the evidence snapshot | ExternalAuditor |
| GET    | `/licensing/reports/compliance-summary` | Computed compliance posture summary (counts and reimbursement totals) | ComplianceAdmin, ComplianceOfficer, HRPartner, ExternalAuditor |
| POST   | `/licensing/_clock/set_current_utc` | Set the logical clock (ISO 8601 UTC) and run the expiry sweep | ComplianceAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the §2 and §3 narratives; this table is the identifier-to-status map only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_LICENSE_SUSPENDED` | 403 Forbidden |
| `ERR_EMPLOYEE_SCREENING_FLAGGED` | 403 Forbidden |
| `ERR_SOD_SAME_USER` | 403 Forbidden |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_LICENSE` | 409 Conflict |
| `ERR_DUPLICATE_ROLE_REQUIREMENT` | 409 Conflict |
| `ERR_DUPLICATE_LICENSE_TYPE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_CASE_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_VERIFICATION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_VERIFICATION_DATE` | 422 Unprocessable Entity |
| `ERR_INVALID_DATES` | 422 Unprocessable Entity |
| `ERR_VALIDITY_WINDOW_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_VERIFICATION_OUT_OF_ORDER` | 422 Unprocessable Entity |
| `ERR_INVALID_AUDIT_PERIOD` | 422 Unprocessable Entity |
| `ERR_AUDIT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_AUDIT_PERIOD_NOT_CLOSED` | 422 Unprocessable Entity |
| `ERR_SCREENING_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_LICENSE_NOT_RENEWABLE` | 409 Conflict |
| `ERR_LICENSE_NOT_CE_ELIGIBLE` | 409 Conflict |
| `ERR_CE_HOURS_INSUFFICIENT` | 409 Conflict |
| `ERR_CLAIM_EXCEEDS_HARD_CAP` | 422 Unprocessable Entity |
| `ERR_COMMITTED_CAP_EXCEEDED` | 402 Payment Required |
