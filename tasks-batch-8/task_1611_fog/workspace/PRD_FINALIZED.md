# FOG Ordinance API — Product Requirements Document

## 1. Introduction

Municipal sewer systems tend to fail in a characteristic way: slowly, invisibly, and expensively. Fats, oils, and grease discharged by food-service establishments congeal inside collection lines until a main blocks, a basement floods, or a surcharge reaches a waterway — and by the time crews respond, the question of *who* contributed to the blockage is as urgent as the cleanup itself. This document specifies the FOG (Fats/Oils/Grease) Ordinance Compliance Program API, the system of record through which a city registers food-service establishments, classifies their grease risk, sizes and commissions their grease interceptors, enforces pumping schedules through manifest verification, scores inspections and escalates violations, investigates blockages and recovers cleanup costs, permits waste haulers and tracks disposal, adjudicates variance requests, and runs public-education campaigns.

The program is audit-driven and deliberately segregation-of-duties minded. Field inspectors gather evidence but cannot excuse it; compliance officers escalate and dismiss but never inspect the establishments they judge; program administrators run the registry, hauler permitting, campaigns, sweeps, and the program clock without touching individual enforcement decisions. Most workflows here are cyclic rather than one-shot — establishments drift in and out of delinquency as pumping evidence arrives, haulers are suspended and reinstated, variance requests cycle through information demands — so the API treats derived compliance posture as a continuously recomputed quantity rather than a label anyone sets by hand.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request missing either header, or carrying a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly five roles: `ProgramAdmin`, `Inspector`, `ComplianceOfficer`, `FseContact`, and `HaulerAdmin`. Access to each operation is restricted by role; a caller whose role is not listed for the endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Three of the roles carry an **opaque** identity. When `X-User-Role` is `ProgramAdmin`, `Inspector`, or `ComplianceOfficer`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `inspector_user_id` on a submitted inspection, `approved_by_user_id` on a decided interceptor or variance, `commissioned_by_user_id` on a commissioned interceptor, or `dismissed_by_user_id` on a dismissed violation — but it never compares the value to any entity's `id`.

The remaining two roles are **entity-backed**. When `X-User-Role` is `FseContact`, the `X-User-ID` is the `id` of the acting Establishment; ownership checks on any resource that references an establishment compare the resource's establishment foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). When `X-User-Role` is `HaulerAdmin`, the `X-User-ID` is the `id` of the acting Hauler, and the same comparison applies against hauler foreign keys. In practice, an establishment contact may propose interceptors, submit pump manifests, file variance requests, answer information demands, and pay cost shares only for its own establishment, and its reads are limited to its own establishment's resources; a hauler administrator may file disposal records only for its own hauler, and its reads are limited to its own hauler, the manifests naming that hauler, and its own disposal records.

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

### 2.3. Pagination

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Program Clock

Every time-dependent rule in the program — cure deadlines, insurance expiry, pumping delinquency, campaign windows — reads a single server-side logical clock, never the wall clock. Before any clock-setting call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z. A `ProgramAdmin`-only clock-setting capability advances the logical clock to a supplied `to_iso8601` instant. The new value must be strictly after the current value; a proposed reading at or before the current clock is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422). A successful call returns the new reading as `current_utc`. All datetime comparisons in this document operate at second precision.

### 2.5. Common Resource Properties

All primary resources carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification to the resource.
- `version` (integer): a system-managed integer that increments with every modification to the resource.

Two record types are immutable once created — the Inspection and the DisposalRecord. They carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, because their contents never change after creation.

### 2.6. Optimistic Concurrency Control

Two write operations are pinned to the establishment's version counter, and both require the request to carry `expected_establishment_version` holding the client's last-observed `version` of the target establishment. The first is the establishment profile update: if the supplied value no longer matches the establishment's current `version` — because a variance approval cascade or an earlier profile update has advanced it since the client last read the record — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must rebase on a fresh read before reapplying. The second is variance approval, which pins a requested pumping frequency onto the establishment: the same comparison is made against the establishment's current `version`, and a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), because the compliance profile underpinning the review — risk class, posture, prior variance windows — may have changed since the reviewer observed it. Endpoints other than these two do not accept a version field.

### 2.7. Derived Posture and Cascading Reconciliation

An establishment's `compliance_status` is never set directly; it is recomputed from underlying facts whenever those facts change. The recomputation fires when a violation of the establishment is created, escalated, resolved, or dismissed; when one of its pump manifests is verified; when one of its variance requests is approved; when the establishment's own profile is updated; and when the periodic compliance sweep runs. Each reconciliation that alters an establishment's stored fields is a mutation in its own right: it refreshes the establishment's `updated_at` and advances its `version`.

Reconciliation also cascades across aggregates. When a violation escalates to `CITATION`, the owning establishment's posture may enter `SUSPENDED`, and entering `SUSPENDED` force-denies every open variance request of that establishment. When a hauler is suspended — manually or automatically — every still-`SUBMITTED` pump manifest naming that hauler is rejected in the same motion. These cascades are part of the triggering operation, not deferred background work.

### 2.8. Monetary Values, Rounding, and Precision

All monetary quantities are integer cents — violation fines (`fine_cents`), blockage money (`total_cleanup_cost_cents`, `share_cents`), and campaign money (`budget_cents`, `remaining_budget_cents`, `cost_cents`) alike. Where division is required — cost-share apportionment at blockage assessment — each individual share is rounded half-up to whole cents *before* any remainder is reconciled; summing the unrounded shares and rounding only the total is forbidden, because it yields different cents. Interceptor capacities are whole gallons, with the ceiling taken at each sizing variant before the variants are compared. An establishment's `risk_score` is carried at one decimal place, and the risk-class thresholds compare against that exact value rather than any integer-rounded form.

### 2.9. Request Validation Order

When several rules could reject the same request, the server evaluates checks in a fixed order and reports the first failure:

1. Authentication: the `X-User-ID` and `X-User-Role` headers are present and the role is recognized (`ERR_UNAUTHENTICATED`).
2. Request-body shape: required fields present, no type violations, enum values in range, the conditional requirement that `requested_frequency_days` is present exactly when the variance scope is `PUMPING_FREQUENCY` and absent otherwise, and window ends lying after their starts (`ERR_INVALID_REQUEST`).
3. Role authorization for the endpoint (`ERR_UNAUTHORIZED`).
4. Ownership for entity-backed roles (`ERR_FORBIDDEN_OWNERSHIP`).
5. Existence of every referenced identifier, in path and body alike — establishments, interceptors, haulers, manifests, inspections, violations, blockage events, variance requests, campaigns, outreach events, and the establishments named inside blockage contributions (`ERR_NOT_FOUND`).
6. From-state validity for the requested transition, including terminal-state lockdowns and attempts to pay an already-paid contribution (`ERR_INVALID_STATE`).
7. Optimistic concurrency on the two version-pinned endpoints (`ERR_STALE_VERSION`).
8. Segregation of duties (`ERR_SOD_VIOLATION`).
9. Regulatory gates: hauler `PERMITTED` at manifest verification and disposal filing (`ERR_HAULER_NOT_PERMITTED`), interceptor `ACTIVE` at manifest submission (`ERR_INTERCEPTOR_NOT_ACTIVE`), hauler insurance unexpired at permitting (`ERR_INSURANCE_EXPIRED`), establishment not `SUSPENDED` at variance approval (`ERR_ESTABLISHMENT_SUSPENDED`).
10. Manifest cross-reference coherence at verification, in this sequence: interceptor ownership (`ERR_INTERCEPTOR_MISMATCH`), disposal record existence (`ERR_DISPOSAL_RECORD_MISSING`), disposal volume tolerance (`ERR_DISPOSAL_DISCREPANCY`).
11. Temporal rules (`ERR_ESCALATION_NOT_DUE`, `ERR_VARIANCE_WINDOW_OVERLAP`, `ERR_CAMPAIGN_WINDOW_CONFLICT`, `ERR_OUTSIDE_CAMPAIGN_WINDOW`, `ERR_CLOCK_REGRESSION`).
12. Uniqueness and structural constraints (`ERR_DUPLICATE_MANIFEST`, `ERR_DUPLICATE_DISPOSAL`, `ERR_VARIANCE_ALREADY_OPEN`, `ERR_INTERCEPTOR_UNDERSIZED`, `ERR_NO_CONTRIBUTORS`, `ERR_WEIGHTS_INVALID`).
13. Fiscal checks, last of all (`ERR_CAMPAIGN_BUDGET_EXCEEDED`, `ERR_COST_SHARE_UNPAID`).

The ordering matters wherever checks overlap. A campaign event that falls outside its campaign window and also overshoots the budget reports `ERR_OUTSIDE_CAMPAIGN_WINDOW`, never the budget error. A variance approval carrying a stale version reports `ERR_STALE_VERSION` even if the establishment also happens to be `SUSPENDED`. A manifest verification against an unpermitted hauler reports `ERR_HAULER_NOT_PERMITTED` before any cross-reference question is asked.

## 3. Business Logic & Workflows

### 3.1. Establishment Enrollment and Risk Classification

Everything begins with the registry. A `ProgramAdmin` enrolls a food-service establishment by supplying its `name`, `street_address`, `seating_capacity` (a non-negative integer), `fryer_count` (a non-negative integer), and `cuisine_profile` — one of `LOW_GREASE`, `MEDIUM_GREASE`, or `HIGH_GREASE`. The boolean `has_charbroiler` is optional and defaults to false when omitted. At enrollment the establishment's `compliance_status` is `COMPLIANT`, its `open_violation_count` — the count of its violations standing at `NOTICED` or `CITATION` — and its `missed_pump_windows` are zero, and both `last_verified_pump_at` and `variance_override_frequency_days` are null.

Enrollment also computes the establishment's risk classification, and the same computation reruns whenever a profile update changes any of the four risk inputs. The `risk_score` is the sum of three components: a seating contribution of one-tenth of a point per seat, capped at 40 points; an equipment contribution of 10 points per deep fryer plus a further 10 points when a charbroiler is installed, capped at 30 points; and a cuisine contribution of 10 points for `LOW_GREASE`, 20 points for `MEDIUM_GREASE`, or 30 points for `HIGH_GREASE`. The resulting score ranges from 0 to 100 and is kept at one decimal place. The `risk_class` derives from the exact score: at least 70 is `HIGH`, at least 40 but below 70 is `MEDIUM`, and anything below 40 is `LOW`. The boundaries are inclusive — a score of exactly 70 classifies `HIGH`, and exactly 40 classifies `MEDIUM`.

Risk class drives the mandatory pumping cadence. An establishment's `pumping_frequency_days` is the value of its `variance_override_frequency_days` when one has been set by an approved variance, and otherwise the risk-table value for its class: 90 days for `HIGH`, 180 days for `MEDIUM`, and 365 days for `LOW`.

A `ProgramAdmin` may later update any subset of the profile fields — `name`, `street_address`, `seating_capacity`, `fryer_count`, `has_charbroiler`, `cuisine_profile` — in a single request that must also carry the `expected_establishment_version` described in §2.6. When any of `seating_capacity`, `fryer_count`, `has_charbroiler`, or `cuisine_profile` changes, the risk classification is recomputed; `pumping_frequency_days` and the compliance posture are recomputed as well, and the establishment's `version` advances by one. Reading a single establishment returns the full record, including the computed `risk_score`, `risk_class`, `compliance_status`, `pumping_frequency_days`, `pumping_overdue`, and `missed_pump_windows`.

### 3.2. Interceptor Sizing, Approval, and Commissioning

An establishment contact or a `ProgramAdmin` proposes a grease interceptor by naming the owning `establishment_id`, a `nominal_capacity_gal` greater than zero, and optionally a `measured_flow_gpm` — a field-measured peak flow in gallons per minute which, when present, must be greater than zero. A newly proposed interceptor sits in `PROPOSED` status. At proposal time the server computes `provisional_required_gal`, the profile-only sizing figure, while `required_min_capacity_gal` and `sizing_method` remain null until sizing approval.

Provisional sizing works purely from the establishment's profile. Take 2 gallons per seat, add 15 gallons per deep fryer, add 40 gallons when the establishment has a charbroiler, and add a cuisine adder of 0 gallons for `LOW_GREASE`, 25 gallons for `MEDIUM_GREASE`, or 50 gallons for `HIGH_GREASE`; round the sum up to the next whole gallon; the provisional requirement is that figure or 50 gallons, whichever is larger. When a `measured_flow_gpm` has been supplied, a second variant applies: the measured requirement is the measured flow multiplied by a 30-minute retention time, again rounded up to the next whole gallon.

Sizing approval belongs to a `ComplianceOfficer` and is allowed only from `PROPOSED`. At approval the server fixes the final sizing: `required_min_capacity_gal` is the provisional requirement when no measured flow was supplied, and otherwise the larger of the two variants; `sizing_method` is `MEASURED` only when measured flow was supplied *and* the measured variant strictly exceeds the provisional one, and `PROVISIONAL` in every other case. Consider a profile that yields 495 gallons against a measured 20 gallons per minute: the measured variant computes to 600 gallons, so the interceptor is governed as `MEASURED` at 600 gallons. The approval is rejected with `ERR_INTERCEPTOR_UNDERSIZED` (HTTP 422) when `nominal_capacity_gal` is smaller than that final requirement. A successful approval moves the interceptor from `PROPOSED` to `APPROVED`, stamps `approved_by_user_id` with the officer's identity, and freezes both sizing fields.

Commissioning is the field-verified installation sign-off, performed by an `Inspector`, moving the interceptor from `APPROVED` to `ACTIVE` and recording `commissioned_by_user_id`. Only an `ACTIVE` interceptor may be named on a new pump manifest; submitting against one that is still `PROPOSED`, or merely `APPROVED`, is rejected with `ERR_INTERCEPTOR_NOT_ACTIVE` (HTTP 409). Interceptors can be listed with optional `establishment_id` and `status` filters, or read individually.

### 3.3. Inspections, Scoring, and Violation Escalation

An `Inspector` records a site inspection by supplying the `establishment_id` and an `items` array of findings, where each finding pairs a `category` — one of `GREASE_TRAP_MAINTENANCE`, `RECORD_KEEPING`, `STRUCTURAL`, or `BMP_PRACTICES` — with a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`. The array may be empty. The submitting inspector's identity is captured as `inspector_user_id`. Scoring happens atomically at creation: each `MINOR` finding deducts 3 points, each `MAJOR` deducts 8, and each `CRITICAL` deducts 20, and the inspection's `score` is 100 minus the total deductions, never below zero. An inspection has `passed` when its score is at least 70 — exactly 70 passes, while 69 fails. Inspections are immutable evidence: once created they never change, and they carry no `updated_at` or `version`. Inspections can be listed with an optional `establishment_id` filter, or read individually.

A failing inspection automatically opens a violation. The violation inherits `establishment_id` from the inspected establishment and points back to its source through `inspection_id`; its `severity` is the highest severity present among the findings, with `CRITICAL` ranking above `MAJOR` above `MINOR`. It opens in `NOTICED` status with `fine_cents` at zero, a `cure_deadline` set from its creation time according to severity — 30 days for `MINOR`, 14 days for `MAJOR`, 3 days for `CRITICAL` — and `recorded_by_user_id` holding the identity of the inspector whose inspection created it. The establishment's `open_violation_count` rises by one, and its posture is recomputed. A passing inspection opens no violation.

Escalation turns notice into citation. A `ComplianceOfficer` may escalate a `NOTICED` violation once the logical clock has reached its `cure_deadline`; attempting it earlier is rejected with `ERR_ESCALATION_NOT_DUE` (HTTP 409), while escalating at exactly the deadline instant is allowed. Escalation stamps `escalated_at`, sets `fine_cents` by severity — 10000 cents for `MINOR`, 50000 cents for `MAJOR`, 250000 cents for `CRITICAL` — and recomputes the establishment's posture, which may now enter `SUSPENDED` and trigger the variance cascade described in §3.5.

Two outcomes close a violation, and both are available from either `NOTICED` or `CITATION`. An `Inspector` marks the problem corrected, moving the violation to `RESOLVED` with `resolved_at` stamped to the current clock. A `ComplianceOfficer` may instead dismiss it — but segregation of duties forbids dismissing a violation whose `recorded_by_user_id` equals the caller's own identity, a rejection carried by `ERR_SOD_VIOLATION` (HTTP 403); a successful dismissal stamps `dismissed_at` and records `dismissed_by_user_id`. Either outcome decrements the establishment's `open_violation_count` by one and recomputes its posture. `RESOLVED` and `DISMISSED` are terminal: closed violations accept no further transitions. Violations can be listed with optional `establishment_id`, `inspection_id`, and `status` filters, or read individually.

### 3.4. Hauler Permitting, Pumping Manifests, and Disposal Reconciliation

Waste haulers enter the program through a `ProgramAdmin` registration carrying the company `name`, a municipal `permit_number` that must be unique across all haulers, and an `insurance_expires_on` timestamp; the hauler starts in `APPLIED` status with its `mismatch_count` at zero. Permitting, also by a `ProgramAdmin`, requires `insurance_expires_on` to lie strictly after the current logical clock — insurance that has already lapsed, or that lapses at exactly the current instant, fails with `ERR_INSURANCE_EXPIRED` (HTTP 422) — and moves the hauler from `APPLIED` to `PERMITTED`.

From `PERMITTED`, a hauler's standing can change in three ways. A `ComplianceOfficer` may suspend it, moving it to `SUSPENDED`; the same transition fires automatically the moment the hauler's `mismatch_count` reaches 3, as described below. Either way, suspension cascades immediately: every pump manifest still in `SUBMITTED` status that names the hauler is rejected with `reject_reason` `HAULER_SUSPENDED`. A suspended hauler may be reinstated by a `ComplianceOfficer`, returning to `PERMITTED` with its `mismatch_count` reset to zero. Finally, a `ComplianceOfficer` may revoke the permit of a hauler in either `PERMITTED` or `SUSPENDED`, moving it to the terminal `REVOKED` status.

With a permitted hauler and an active interceptor in place, the establishment contact submits a pump manifest naming `establishment_id`, `interceptor_id`, `hauler_id`, the `pump_date`, and the `pumped_volume_gal`, which must be greater than zero. The interceptor must be `ACTIVE` (otherwise `ERR_INTERCEPTOR_NOT_ACTIVE`), and at most one manifest may exist for a given interceptor and `pump_date` — a duplicate is rejected with `ERR_DUPLICATE_MANIFEST` (HTTP 409). The manifest opens in `SUBMITTED` status, with `submitted_by_user_id` recording the submitting contact's identity. Manifests can be listed with optional `establishment_id`, `hauler_id`, `interceptor_id`, and `status` filters, or read individually.

The hauler's half of the loop is the disposal record, filed by a `HaulerAdmin` for its own hauler with the `hauler_id`, the `manifest_id` it settles, the `disposed_volume_gal` (greater than zero), the receiving facility's `disposal_site_name`, and the `disposed_at` timestamp. The hauler must currently be `PERMITTED` — filing under any other status is rejected with `ERR_HAULER_NOT_PERMITTED` (HTTP 409) — the named manifest must still be `SUBMITTED`, and at most one disposal record may exist per manifest, enforced with `ERR_DUPLICATE_DISPOSAL` (HTTP 409). Disposal records are immutable once filed. They can be listed with optional `hauler_id` and `manifest_id` filters, or read individually.

Verification is the `Inspector`'s reconciliation of the two halves, allowed only from `SUBMITTED`. Four checks run in a fixed sequence, and the first failure ends the review: the named hauler must currently be `PERMITTED` (`ERR_HAULER_NOT_PERMITTED`); the named interceptor must belong to the manifest's establishment (`ERR_INTERCEPTOR_MISMATCH`, HTTP 422); a disposal record must exist for the manifest (`ERR_DISPOSAL_RECORD_MISSING`, HTTP 422); and the disposal volume must reconcile with the pumped volume — the absolute difference between `disposed_volume_gal` and `pumped_volume_gal`, divided by `pumped_volume_gal`, must not exceed 0.05, so a ratio of exactly 0.05 passes and only a strictly larger ratio is rejected as `ERR_DISPOSAL_DISCREPANCY` (HTTP 422). A verified manifest moves to `VERIFIED`, sets the establishment's `last_verified_pump_at` to the manifest's `pump_date`, and recomputes the establishment's posture — a fresh verification is the ordinary way a `DELINQUENT` establishment returns to good standing.

Rejection, likewise an `Inspector`'s action from `SUBMITTED`, takes a `reason_code` — one of `DISPOSAL_MISMATCH`, `MISSING_DISPOSAL_RECORD`, `HAULER_SUSPENDED`, or `OTHER` — which is stored on the manifest as `reject_reason`. Rejection carries teeth when the reason is `DISPOSAL_MISMATCH`: the hauler's `mismatch_count` increments by one, and a hauler whose count thereby reaches 3 immediately transitions from `PERMITTED` to `SUSPENDED`, which in turn cascades a `HAULER_SUSPENDED` rejection onto every other still-`SUBMITTED` manifest naming that hauler. Both `VERIFIED` and `REJECTED` are terminal.

### 3.5. Pumping Delinquency and the Compliance Sweep

The program tracks pumping delinquency through two complementary lenses, and confusing them is the classic implementation mistake. The forward-looking lens is the boolean `pumping_overdue`: take the establishment's pumping baseline — its `last_verified_pump_at` when one is set, otherwise its `created_at` — and the establishment is overdue when the logical clock is strictly later than the baseline plus `pumping_frequency_days`. Sitting exactly at the deadline instant is not yet overdue. Because the baseline is the *most recent* verified pump, a single fresh verification resets it: an establishment that missed windows long ago but pumped recently is not overdue.

The chronological lens is the integer `missed_pump_windows`, a historical replay. Divide the time since the establishment's `created_at` into consecutive half-open windows, each `pumping_frequency_days` long — the first window runs from `created_at` up to but not including `created_at` plus one frequency period, and so on. Count every window that has fully elapsed — its end at or before the current clock — in which no `VERIFIED` manifest's `pump_date` falls. A late pump satisfies only the window it actually lands in, so the same history can legitimately yield a `missed_pump_windows` of one or more while `pumping_overdue` is false.

These lenses feed the establishment's `compliance_status`, recomputed on every triggering event listed in §2.7 under a fixed priority order: `SUSPENDED` whenever any violation of the establishment stands at `CITATION`; otherwise `DELINQUENT` whenever `pumping_overdue` holds; otherwise `WATCH` whenever any violation stands at `NOTICED`; otherwise `COMPLIANT`. The priority is fixed — a citation always dominates delinquency, which always dominates a mere notice.

Entering `SUSPENDED` carries an immediate consequence beyond the label: every variance request of that establishment currently `UNDER_REVIEW` or `INFO_REQUESTED` is denied in the same motion, with `decided_at` stamped to the current clock and `approved_by_user_id` left null. The denial cascade is part of the posture recomputation, not a separate workflow.

The compliance sweep is the `ProgramAdmin`'s batch checkpoint for everything time-driven. A sweep auto-escalates every `NOTICED` violation whose `cure_deadline` has been reached — that is, at or before the current clock — to `CITATION`, applying the same severity-based fine, the same `escalated_at` stamping, and the same posture cascade, variance denials included, as a manual escalation. The sweep then recomputes pumping delinquency for every establishment, and returns two lists: the identifiers of the violations it escalated, in `escalated_violation_ids`, and the identifiers of the establishments it found delinquent, in `delinquent_establishment_ids`.

### 3.6. Blockage Investigation and Cost Recovery

When a sewer main blocks, an `Inspector` opens a blockage event with a `location_description`; the event starts in `REPORTED` status with `reported_by_user_id` recording who called it in, and `total_cleanup_cost_cents` stays null until assessment.

Assessment — again an `Inspector`'s action — fixes the financial facts: the `total_cleanup_cost_cents`, which must be greater than zero, and a `contributions` array in which each entry names an `establishment_id` and an integer `weight_percent`. Three guards apply: every establishment named among the contributions must exist (`ERR_NOT_FOUND`); the array must not be empty (`ERR_NO_CONTRIBUTORS`, HTTP 422); and the weights must sum to exactly 100 (`ERR_WEIGHTS_INVALID`, HTTP 422). For each accepted contribution the server computes a `share_cents` and attaches a `paid_at` that stays null until paid. Apportionment follows a pinned rounding order: each share is the total cleanup cost multiplied by the contribution's weight and divided by 100, rounded half-up to whole cents; then the remainder between the total and the sum of the rounded shares — which may be negative — is assigned to the contribution carrying the largest `weight_percent`, with ties resolved in favor of the contribution whose establishment was created earliest. Assessment records `assessed_by_user_id` and moves the event from `REPORTED` to `ASSESSED`.

Collection is per-contribution. An establishment contact pays its own establishment's share by naming its `establishment_id`; the server stamps that contribution's `paid_at` with the current clock. Attempting to pay a contribution that has already been paid is an invalid-state rejection, as is paying on an event that has not been assessed.

Closure belongs to a `ComplianceOfficer` and is deliberately two-keyed: the closer's identity must differ from `assessed_by_user_id` (`ERR_SOD_VIOLATION`, HTTP 403), and every contribution must show a non-null `paid_at` (`ERR_COST_SHARE_UNPAID`, HTTP 409). A successful close records `closed_by_user_id` and moves the event from `ASSESSED` to the terminal `CLOSED` status.

### 3.7. Variance Requests

An establishment that believes the ordinance's default cadence or sizing wrong for its circumstances files a variance request through its contact. The filing names the `establishment_id`, a `scope` of `PUMPING_FREQUENCY` or `INTERCEPTOR_SIZE`, a written `justification`, and a requested window running from `effective_from` to `effective_to` — a half-open interval, with `effective_to` required to lie after `effective_from`. When the scope is `PUMPING_FREQUENCY`, a `requested_frequency_days` greater than zero is required; for `INTERCEPTOR_SIZE` it must be absent entirely. At most one open request — one in `UNDER_REVIEW` or `INFO_REQUESTED` — may exist per establishment and scope; a second filing collides with `ERR_VARIANCE_ALREADY_OPEN` (HTTP 409). A new request starts in `UNDER_REVIEW`.

Review is a dialogue. A `ComplianceOfficer` may push a request from `UNDER_REVIEW` to `INFO_REQUESTED` to demand more material; the applicant answers by supplying a replacement `justification`, which returns the request to `UNDER_REVIEW`. Naturally, only the owning establishment's contact may answer (`ERR_FORBIDDEN_OWNERSHIP` otherwise), and the cycle may repeat as needed.

Approval is the most heavily guarded decision in the program, and its checks run in a fixed order. The request must still be `UNDER_REVIEW`. The payload must carry an `expected_establishment_version` matching the establishment's current `version`, else `ERR_STALE_VERSION` (HTTP 412). The establishment's `compliance_status` must not be `SUSPENDED` (`ERR_ESTABLISHMENT_SUSPENDED`, HTTP 409). And no other `APPROVED` variance for the same establishment and scope may have a window overlapping the requested one — the windows are half-open, so one request's `effective_from` falling exactly on another's `effective_to` is adjacency rather than overlap, while a genuine collision is rejected with `ERR_VARIANCE_WINDOW_OVERLAP` (HTTP 409). On approval the server records `approved_by_user_id` and stamps `decided_at`; for the `PUMPING_FREQUENCY` scope it also writes `requested_frequency_days` into the establishment's `variance_override_frequency_days`, which recomputes `pumping_frequency_days`; the establishment's `version` advances by one, and its posture is recomputed — a freshly granted longer cadence can by itself lift an establishment out of `DELINQUENT`.

Denial is simpler: a `ComplianceOfficer` may deny from either `UNDER_REVIEW` or `INFO_REQUESTED`, stamping `decided_at`. As §3.5 describes, the system itself denies any still-open request the moment the establishment's posture enters `SUSPENDED`, stamping `decided_at` and leaving `approved_by_user_id` null. `APPROVED` and `DENIED` are both terminal. Requests can be listed with optional `establishment_id`, `status`, and `scope` filters, or read individually.

### 3.8. Education Campaigns and Outreach Budgeting

The program's preventive arm is the education campaign. A `ProgramAdmin` creates one with a `name`, an `outreach_zone` label, a `start_date`, an `end_date` that must lie after the start, and a `budget_cents` of zero or more; the campaign's `remaining_budget_cents` is initialized to the full `budget_cents`. To keep outreach efforts from cannibalizing one another, a new campaign is rejected with `ERR_CAMPAIGN_WINDOW_CONFLICT` (HTTP 409) when its window overlaps another campaign in the same `outreach_zone` — or even sits within 14 days of one.

Outreach events are recorded under their parent campaign, so the campaign's existence is confirmed before any event-level rule is evaluated, and the created event's `campaign_id` is taken from the parent rather than the payload. Each event carries an `event_date` that must fall within the campaign's inclusive window from `start_date` to `end_date` (`ERR_OUTSIDE_CAMPAIGN_WINDOW`, HTTP 422), a `venue_name`, an `attendance_count` of zero or more, and a `cost_cents` of zero or more. The fiscal check runs after the temporal one: `cost_cents` must not exceed the campaign's `remaining_budget_cents`, though a cost exactly equal to the remaining budget is permitted; anything larger is rejected with `ERR_CAMPAIGN_BUDGET_EXCEEDED` (HTTP 422). A recorded event starts in `RECORDED` status, and the campaign's remaining budget drops by its `cost_cents` — equivalently, `remaining_budget_cents` is always the budget minus the summed costs of the campaign's `RECORDED` events.

If an event was logged in error, a `ProgramAdmin` voids it, moving it from `RECORDED` to the terminal `VOIDED` status. Voiding is a compensating credit: the event's `cost_cents` returns to the campaign's `remaining_budget_cents`, so a recorded-then-voided event leaves the budget exactly where it stood before the event. `VOIDED` events are excluded from the budget sum. Events can be listed with optional `campaign_id` and `status` filters, or read individually.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource, trigger a workflow action, or run a batch checkpoint return a `200 OK` status code. The table below summarizes the HTTP contract only; request payloads, response content, validation conditions, and side effects are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/establishments` | Register a food-service establishment; computes risk classification, pumping frequency, and initial posture | ProgramAdmin |
| GET | `/establishments/{id}` | Read one establishment including computed posture and delinquency fields | ProgramAdmin, Inspector, ComplianceOfficer, FseContact |
| PATCH | `/establishments/{id}` | Update profile fields; recomputes risk class, pumping frequency, and posture; OCC-pinned | ProgramAdmin |
| POST | `/interceptors` | Propose a grease interceptor; provisional sizing computed; status PROPOSED | FseContact, ProgramAdmin |
| GET | `/interceptors` | List interceptors, filterable by establishment and status | ProgramAdmin, Inspector, ComplianceOfficer, FseContact |
| GET | `/interceptors/{id}` | Read one interceptor | ProgramAdmin, Inspector, ComplianceOfficer, FseContact |
| POST | `/interceptors/{id}/approve` | Sizing approval: fixes required capacity and sizing method; rejects undersized proposals | ComplianceOfficer |
| POST | `/interceptors/{id}/commission` | Installation approval: field-verified interceptor goes ACTIVE and becomes pumpable | Inspector |
| POST | `/inspections` | Record a scored inspection (immutable); failing score auto-creates a NOTICED violation | Inspector |
| GET | `/inspections` | List inspections, filterable by establishment | ProgramAdmin, Inspector, ComplianceOfficer |
| GET | `/inspections/{id}` | Read one inspection | ProgramAdmin, Inspector, ComplianceOfficer |
| GET | `/violations` | List violations, filterable by establishment, source inspection, and status | ProgramAdmin, Inspector, ComplianceOfficer, FseContact |
| GET | `/violations/{id}` | Read one violation | ProgramAdmin, Inspector, ComplianceOfficer, FseContact |
| POST | `/violations/{id}/escalate` | Escalate NOTICED to CITATION once the cure deadline has been reached; sets the fine; posture may enter SUSPENDED | ComplianceOfficer |
| POST | `/violations/{id}/resolve` | Mark a violation corrected | Inspector |
| POST | `/violations/{id}/dismiss` | Dismiss a violation; segregation of duties vs the recording inspector | ComplianceOfficer |
| POST | `/pump-manifests` | Submit a pumping manifest; interceptor must be ACTIVE; one manifest per interceptor per pump date | FseContact |
| GET | `/pump-manifests` | List manifests, filterable by establishment, hauler, interceptor, and status | ProgramAdmin, Inspector, ComplianceOfficer, FseContact, HaulerAdmin |
| GET | `/pump-manifests/{id}` | Read one manifest | ProgramAdmin, Inspector, ComplianceOfficer, FseContact, HaulerAdmin |
| POST | `/pump-manifests/{id}/verify` | Verify a manifest against hauler permit, interceptor ownership, and disposal reconciliation | Inspector |
| POST | `/pump-manifests/{id}/reject` | Reject a manifest with a reason; DISPOSAL_MISMATCH increments the hauler's mismatch count and may auto-suspend it | Inspector |
| POST | `/haulers` | Register a waste hauler; status APPLIED | ProgramAdmin |
| GET | `/haulers/{id}` | Read one hauler | ProgramAdmin, Inspector, ComplianceOfficer, HaulerAdmin |
| POST | `/haulers/{id}/permit` | Grant the operating permit; insurance must be unexpired | ProgramAdmin |
| POST | `/haulers/{id}/suspend` | Suspend a permitted hauler; its SUBMITTED manifests are auto-rejected | ComplianceOfficer |
| POST | `/haulers/{id}/reinstate` | Reinstate a suspended hauler; resets the mismatch count to zero | ComplianceOfficer |
| POST | `/haulers/{id}/revoke` | Revoke a hauler permit permanently | ComplianceOfficer |
| POST | `/disposal-records` | Record disposal at a receiving site; hauler must be PERMITTED; manifest must be SUBMITTED; one record per manifest | HaulerAdmin |
| GET | `/disposal-records` | List disposal records, filterable by hauler and manifest | ProgramAdmin, Inspector, ComplianceOfficer, HaulerAdmin |
| GET | `/disposal-records/{id}` | Read one disposal record | ProgramAdmin, Inspector, ComplianceOfficer, HaulerAdmin |
| POST | `/blockage-events` | Report a sewer blockage; status REPORTED | Inspector |
| GET | `/blockage-events/{id}` | Read one blockage event including contributions and computed shares | ProgramAdmin, Inspector, ComplianceOfficer, FseContact |
| POST | `/blockage-events/{id}/assess` | Fix total cleanup cost and contributing establishments; computes per-contribution shares | Inspector |
| POST | `/blockage-events/{id}/pay` | Pay the calling establishment's assessed share | FseContact |
| POST | `/blockage-events/{id}/close` | Close once all shares are paid; closer must differ from assessor | ComplianceOfficer |
| POST | `/variance-requests` | Request a variance; at most one open variance per establishment and scope; starts UNDER_REVIEW | FseContact |
| GET | `/variance-requests` | List variance requests, filterable by establishment, status, and scope | ProgramAdmin, Inspector, ComplianceOfficer, FseContact |
| GET | `/variance-requests/{id}` | Read one variance request | ProgramAdmin, Inspector, ComplianceOfficer, FseContact |
| POST | `/variance-requests/{id}/request-info` | Ask the applicant for more information | ComplianceOfficer |
| POST | `/variance-requests/{id}/provide-info` | Applicant supplies the requested information; returns to UNDER_REVIEW | FseContact |
| POST | `/variance-requests/{id}/approve` | Approve a variance; OCC-pinned to the establishment version; writes the frequency override for PUMPING_FREQUENCY scope | ComplianceOfficer |
| POST | `/variance-requests/{id}/deny` | Deny a variance | ComplianceOfficer |
| POST | `/campaigns` | Create an education campaign; zone windows must not overlap or sit within 14 days of another campaign in the same zone | ProgramAdmin |
| GET | `/campaigns/{id}` | Read one campaign including remaining budget | ProgramAdmin, Inspector, ComplianceOfficer |
| POST | `/campaigns/{id}/events` | Record an outreach event; debits the campaign budget; event date must fall inside the campaign window | ProgramAdmin |
| GET | `/outreach-events` | List outreach events, filterable by campaign and status | ProgramAdmin, Inspector, ComplianceOfficer |
| GET | `/outreach-events/{id}` | Read one outreach event | ProgramAdmin, Inspector, ComplianceOfficer |
| POST | `/outreach-events/{id}/void` | Void an event; credits its cost back to the campaign budget | ProgramAdmin |
| POST | `/sweeps/run` | Compliance sweep checkpoint: auto-escalates overdue NOTICED violations to CITATION with the posture cascade; recomputes pumping delinquency for all establishments | ProgramAdmin |
| POST | `/_clock/set_current_utc` | Test-driving capability: sets the logical clock; the new value must be strictly after the current one | ProgramAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue enumerates only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_HAULER_NOT_PERMITTED` | 409 |
| `ERR_INTERCEPTOR_NOT_ACTIVE` | 409 |
| `ERR_INSURANCE_EXPIRED` | 422 |
| `ERR_ESTABLISHMENT_SUSPENDED` | 409 |
| `ERR_INTERCEPTOR_MISMATCH` | 422 |
| `ERR_DISPOSAL_RECORD_MISSING` | 422 |
| `ERR_DISPOSAL_DISCREPANCY` | 422 |
| `ERR_DUPLICATE_MANIFEST` | 409 |
| `ERR_DUPLICATE_DISPOSAL` | 409 |
| `ERR_VARIANCE_ALREADY_OPEN` | 409 |
| `ERR_VARIANCE_WINDOW_OVERLAP` | 409 |
| `ERR_ESCALATION_NOT_DUE` | 409 |
| `ERR_CAMPAIGN_WINDOW_CONFLICT` | 409 |
| `ERR_OUTSIDE_CAMPAIGN_WINDOW` | 422 |
| `ERR_CAMPAIGN_BUDGET_EXCEEDED` | 422 |
| `ERR_NO_CONTRIBUTORS` | 422 |
| `ERR_WEIGHTS_INVALID` | 422 |
| `ERR_COST_SHARE_UNPAID` | 409 |
| `ERR_INTERCEPTOR_UNDERSIZED` | 422 |
| `ERR_CLOCK_REGRESSION` | 422 |
