# Teleradiology Read Distribution API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for a teleradiology read-distribution platform in the style of a virtual radiology practice. Client hospitals transmit imaging studies to the platform; the platform routes each study according to modality, body-part group, and priority; matches it against radiologists who are licensed in the ordering state, credentialed at the ordering facility, on an active coverage shift, and within their fatigue limits; and tracks the read from receipt through preliminary and final signature to billing. Turnaround-time targets are contractual: a STAT study and a ROUTINE study carry different deadlines, and a late signature generates a per-minute penalty credit on the hospital's invoice.

Three concerns dominate the design. First, reading capacity is a finite pool: assigning a study reserves relative-value-unit (RVU) capacity against a radiologist's fatigue cap, and that reservation is released only when the assignment completes or is released. Second, the platform carries compliance obligations that must be documented, not merely performed — critical findings require a recorded notification and a read-back confirmation from the client hospital, and a material discrepancy between a preliminary and a final read opens a quality case that must be reconciled by someone other than the two signers. Third, all time-dependent behavior (shift activation, credential expiry, notice escalation, invoice windows) is driven by a logical clock rather than the wall clock, so that the entire workflow is deterministic and testable.

The API is mounted under the `/telerad` prefix and is organized into twelve peer resources — client hospitals, radiologists, coverage shifts, routing policies, studies, assignments, reports, discrepancy cases, critical-result notices, credential grants, billing periods, and invoices — with no nested URL hierarchies.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. The platform recognizes exactly five roles: `PlatformAdmin`, `DispatchOps`, `Radiologist`, `ClientHospitalUser`, and `QaReviewer`.

A request with missing or unrecognized headers is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). For entity-backed roles, authentication additionally requires that the supplied identifier resolve to a persisted backing row: when `X-User-Role` is `Radiologist`, `X-User-ID` is the `id` of an acting Radiologist, and ownership checks on any resource that references a radiologist compare the resource's foreign-key field (for example `radiologist_id` on an assignment, report, or notice) to `X-User-ID`. When `X-User-Role` is `ClientHospitalUser`, `X-User-ID` is the `id` of an acting ClientHospital, and ownership checks compare the resource's `hospital_id` to `X-User-ID`; study creation in particular requires the payload's `hospital_id` to equal `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `DispatchOps`, or `QaReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `reconciled_by` on a discrepancy case at reconcile time) but does not compare it to any entity's `id`. A `Radiologist` principal may act only on their own assignments, reports, and critical-result notices; a `ClientHospitalUser` principal may act only on studies and notices belonging to the hospital whose `id` equals their `X-User-ID`.

A request whose role is authenticated but not listed among an endpoint's authorized roles, or that violates one of these ownership bindings, is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the server's wall clock; this envelope field is the platform's only wall-clock read, and all domain timestamps instead come from the logical clock of §2.5.
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

Requests that match no route, or an unsupported method on a matched route, are rejected with `ERR_NOT_FOUND` (HTTP 404); an unexpected server failure yields `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Both parameters must be integers within range — a non-integer value, a `limit` outside 1 through 100, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by `id` ascending. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in the platform — hospitals, radiologists, shifts, policies, studies, assignments, reports, cases, notices, grants, periods, and invoices alike — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that starts at 1 at creation and increments by exactly 1 on every mutation of the resource, including mutations caused by cascades and clock sweeps; at creation `created_at` and `updated_at` coincide.

No entity in this system is exempt: all twelve resource types carry the full common set, and any state transition, side-effect write, or derived-field recomputation that changes a resource refreshes its `updated_at` and increments its `version`.

### 2.5. The Logical Clock and Time-Driven Sweeps

The platform never reads the wall clock for domain data. All timestamps and time-dependent decisions derive from a logical clock whose startup value is exactly 2026-05-01T00:00:00Z. A `PlatformAdmin` may advance the logical clock through an admin-only test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`; the clock is set to whatever valid instant is supplied, which need not be later than its current value. Advancing the clock triggers three sweeps in the same request, atomically: coverage shifts whose window has been entered or passed transition accordingly, credential grants whose last valid day has passed transition to expired, and critical-result notices whose notification or read-back has been outstanding too long are escalated. The same logical clock stamps `received_at` when a study is created, `signed_at` when a report is signed, and `notified_at` and `readback_at` on the communication workflow, and it defines the trailing twenty-four-hour window used by fatigue accounting. Every timestamp the platform stores and returns — the common `created_at` and `updated_at`, a study's `received_at`, `due_at`, and `first_final_signed_at`, a report's `signed_at`, a notice's `notified_at` and `readback_at`, a shift's `starts_at` and `ends_at`, and the `current_utc` returned by the clock endpoint — is rendered as ISO 8601 UTC with exactly three fractional digits, so a whole-second instant renders as, for example, `2026-05-01T00:00:00.000Z`; caller-supplied instants such as shift windows and seed timestamps are parsed and re-serialized in this same form rather than echoed verbatim.

One platform-wide convention sits on top of the clock: the **after-hours window** is 22:00 through 07:00 UTC — inclusive at 22:00, exclusive at 07:00 — evaluated on the wall-clock UTC time-of-day of the relevant timestamp on any covered day. This window classifies coverage shifts and also drives after-hours pricing on invoices.

### 2.6. Precision, Units, and Rounding

RVU quantities are carried at 1 decimal place; per-modality base values and utilization sums are exact at that precision. Monetary results credited to a radiologist (RVU credit) are rounded half-up to 2 decimal places at sign time. All invoice money is integer cents: tier rates, add-ons, penalties, and totals are whole cents, and the only rounding permitted inside invoice composition is the pinned per-unit after-hours rounding described in §3.9, performed with round-half-up at that single point. Deadlines are exact instants at second precision — a study's `due_at` is an exact instant, and breach evaluation compares timestamps strictly. Utilization ratios used to rank candidate radiologists are compared exactly as rational numbers, with no rounding.

### 2.7. Optimistic Concurrency Control

Three write operations guard a parent entity against stale reads, because each can silently supersede state the caller may never have observed. A request to `POST /telerad/routing-policies` must carry `expected_hospital_version` equal to the target hospital's current `version`; creating a policy retires any same-key active policy, so a writer holding a stale hospital version would base its routing decision on a retired policy set. A request to `POST /telerad/billing-periods/{id}/generate-invoice` must carry `expected_billing_period_version` equal to the period's current `version`; regenerating an invoice voids the prior current invoice, so a stale generate would void an invoice the caller never saw. A request to `POST /telerad/assignments` must carry `expected_study_version` equal to the study's current `version`. In all three cases, a missing or non-integer version field is rejected with `ERR_VALIDATION` (HTTP 400), and a mismatch between the supplied value and the parent entity's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read before writing. Endpoints not listed here do not accept a version field.

### 2.8. Validation Order and Resource Resolution

Every request passes through a fixed priority ladder, and a failure at an earlier rung masks every later rung. First (priority 1), authentication headers are validated as in §2.1. Second (priority 2), role authorization and ownership bindings are enforced. Third (priority 3), payload shape: required fields must be present — a required string field must be a non-empty string, and a request body that is not a JSON object is rejected outright — enum fields must hold declared members, and types must be correct, else `ERR_VALIDATION` (HTTP 400); unknown or extra payload fields are ignored, never rejected. Fourth (priority 4), existence: every identifier in the path is resolved left to right, and every body-referenced identifier — `study_id`, `radiologist_id`, `assignment_id`, `hospital_id`, `prelim_report_id`, `final_report_id` — must resolve to an existing row. Each missing resource raises its own domain-specific error: `ERR_HOSPITAL_NOT_FOUND`, `ERR_RADIOLOGIST_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_BILLING_PERIOD_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND` (all HTTP 404). Fifth (priority 5), the optimistic-concurrency checks of §2.7. Sixth (priority 6), state-machine legality: the target resource's state must permit the requested transition, else `ERR_INVALID_STATE` (HTTP 409), with the related-entity gate that study creation and routing require an `ACTIVE` hospital, else `ERR_HOSPITAL_NOT_ACTIVE` (HTTP 409). Seventh (priority 7), licensure and credentialing safety checks — within this rung, licensure is evaluated before credentialing. Eighth (priority 8), structural constraints: uniqueness, overlap, exclusion, shift-coverage, and report-type compatibility rules. Ninth (priority 9), the billing-period reopen grace window. Tenth (priority 10), capacity and fiscal limits on assignment. The sections below attach each rule to the workflow it guards.

### 2.9. Capacity Accounting and Immediate Consistency

Radiologist reading capacity is tracked as a utilization ledger that is recomputed, atomically and in the same request, on every assignment or report mutation and on read. Three derived counters live on every radiologist: `reserved_rvu`, the sum of the reserved RVU over that radiologist's `ACTIVE` assignments; `completed_rvu_24h`, the sum of `credited_rvu` over that radiologist's reports in status `SIGNED` or `SUPERSEDED` whose `signed_at` falls strictly inside the trailing twenty-four hours under the logical clock — a signature exactly twenty-four hours old is excluded, and provisional credit already granted is never clawed back when a preliminary report is later superseded; and `stat_active_count`, the number of the radiologist's `ACTIVE` assignments on `STAT`-priority studies. A fourth counter, `pending_critical_count`, tracks critical-result notices still open against the radiologist — those in `PENDING`, `NOTIFIED`, or `ESCALATED` status. Assignment reserves capacity; signature converts reservation into completed credit; release or cancellation returns the reservation to the pool. All of these cascades land in the same request as their trigger — no deferred or eventual settlement exists anywhere in the system.

## 3. Business Logic & Workflows

### 3.1. Client Hospital Onboarding and Configuration

A `PlatformAdmin` registers a client hospital with a display `name` and the `state_code` of the US state where its imaging is performed. That state code is not decorative: every study the hospital submits inherits it as its licensure scope, and no radiologist without that state in their `license_states` may be assigned the hospital's studies. Each hospital also carries a `credentialing_mode` — `BY_PROXY` (the default) or `INDEPENDENT` — declaring which style of credential grant it accepts for reader privileges, and a `pricing_mode` — `MARGINAL` (the default) or `FLAT_TIER` — selecting the volume-pricing variant used on its invoices.

Turnaround and penalty terms are configured per hospital at registration. The `tat_stat_minutes`, `tat_urgent_minutes`, and `tat_routine_minutes` fields hold the turnaround targets for `STAT`, `URGENT`, and `ROUTINE` studies respectively, defaulting to 60, 240, and 1440 minutes. The `penalty_per_breach_minute_cents` field (default 50) prices each whole minute of lateness, and `breach_penalty_cap_cents` (default 20000) caps the per-study penalty credit.

A hospital begins life in `ONBOARDING` status. Activation by a `PlatformAdmin` moves `ONBOARDING → ACTIVE`, and the same activation also rehabilitates a suspended hospital (`SUSPENDED → ACTIVE`); both increment the hospital's `version` by 1 and refresh `updated_at`. Suspension moves `ACTIVE → SUSPENDED` with the same version and timestamp effects, and while a hospital is `SUSPENDED` every attempt to register a new study for it is rejected with `ERR_HOSPITAL_NOT_ACTIVE`. Only `ACTIVE` hospitals may create or route studies at all. Hospital records can be read individually by `PlatformAdmin`, `DispatchOps`, and `ClientHospitalUser`, and the hospital list — filterable by `status` — is available to `PlatformAdmin` and `DispatchOps`.

### 3.2. Radiologist Roster and Coverage Shifts

Radiologists are onboarded by a `PlatformAdmin` with a `full_name`, a set of `subspecialties` drawn from `NEURORAD`, `MSK`, `BODY`, `CHEST`, `PEDS`, and `GENERAL`, and the `license_states` in which they hold active licenses. Each radiologist carries two capacity knobs: `fatigue_cap_rvu` (default 30.0), the ceiling that the sum of `reserved_rvu` and `completed_rvu_24h` may reach but never exceed, and `max_concurrent_stat` (default 3), the upper bound on that radiologist's concurrently `ACTIVE` assignments on `STAT` studies — at the bound, further STAT assignment rejects. A radiologist's `status` begins `ACTIVE` (a different initial status — `ON_LEAVE` or `INACTIVE` — may be supplied at creation); only `ACTIVE` radiologists are assignable. A `PlatformAdmin` may patch `status`, `fatigue_cap_rvu`, `max_concurrent_stat`, `subspecialties`, or `license_states`, each patch incrementing `version`. Moving `ACTIVE → ON_LEAVE` makes the radiologist ineligible for assignment; `ON_LEAVE → ACTIVE` restores eligibility. Retirement to the terminal `INACTIVE` state is permitted from `ACTIVE` only when the radiologist holds zero `ACTIVE` assignments, and from `ON_LEAVE` unconditionally. The radiologist list supports filtering by `status`, by `state_code`, and by `subspecialty`.

Coverage is expressed through **coverage shifts**: a `PlatformAdmin` schedules a window for a radiologist with `starts_at` and `ends_at` (UTC) plus the `modalities` covered during the window, drawn from `CT`, `MR`, `XR`, `US`, `NM`, and `MG`. The window is a half-open interval — it includes `starts_at` and excludes `ends_at` — and `ends_at` must lie strictly after `starts_at`. One radiologist may not hold two shifts whose half-open windows overlap while both are in `SCHEDULED` or `ACTIVE` status; such a collision is rejected with `ERR_SHIFT_OVERLAP`, though windows that merely touch — one ending exactly where the next begins — are allowed. A shift's computed `after_hours` flag is true whenever its window intersects the platform after-hours window of 22:00 to 07:00 UTC on any covered day.

Shift lifecycle is clock-driven. A shift starts `SCHEDULED`; when the logical clock enters its window (at or after `starts_at` and before `ends_at`), the sweep transitions `SCHEDULED → ACTIVE` and the radiologist becomes shift-eligible for the window's modalities. When the clock reaches or passes `ends_at`, the sweep transitions `ACTIVE → COMPLETED`; a shift whose window was skipped entirely while still `SCHEDULED` transitions directly `SCHEDULED → COMPLETED`. A `PlatformAdmin` may also cancel a `SCHEDULED` shift, moving it to the terminal `CANCELLED` state. Every transition increments the shift's `version` by 1. Shifts can be listed with filters on `radiologist_id` and `status`.

### 3.3. Credentialing at Client Hospitals

Before a radiologist may read for a hospital, they must hold privileges there. A `PlatformAdmin` applies for a **credential grant** naming the `radiologist_id`, the `hospital_id`, a `grant_type` of `BY_PROXY` or `INDEPENDENT`, and an inclusive-day validity window from `valid_from` through `valid_until` (both `YYYY-MM-DD`, both days included); a `valid_until` earlier than `valid_from` is rejected with `ERR_VALIDATION`. The `grant_type` must equal the hospital's `credentialing_mode`; a mismatch is rejected with `ERR_GRANT_TYPE_MISMATCH`. Because the window is inclusive of both days, two grants for the same radiologist–hospital pair in any of the statuses `PENDING`, `GRANTED`, or `SUSPENDED` may not share even a single calendar day; an overlap is rejected with `ERR_GRANT_OVERLAP`.

A grant begins `PENDING`. Granting moves `PENDING → GRANTED`; suspension moves `GRANTED → SUSPENDED`, during which the radiologist fails credential eligibility for that hospital; reinstatement moves `SUSPENDED → GRANTED` but only while the current day has not passed `valid_until` — a grant whose day has passed must expire first, and such a reinstatement attempt is rejected with `ERR_INVALID_STATE`. Revocation moves `GRANTED → REVOKED`, which is terminal. When the logical clock's date passes `valid_until`, the sweep moves `GRANTED → EXPIRED`, again stripping eligibility. An expired grant can be renewed: renewal moves `EXPIRED → PENDING` and installs a fresh `valid_from` and `valid_until` from the payload (again requiring `valid_until` on or after `valid_from`, else `ERR_VALIDATION`), subject to the same inclusive-day overlap check against the pair's other non-terminal grants. Each transition increments the grant's `version`. Grants are listed with filters on `radiologist_id`, `hospital_id`, and `status`. For assignment purposes a credential is "active" only when a grant exists in `GRANTED` status with the current logical day lying on or after `valid_from` and on or before `valid_until`.

### 3.4. Routing Policies and Study Intake

Routing is declared per hospital through **routing policies**. A `PlatformAdmin` creates a policy naming the `hospital_id` plus the match key — `modality`, `body_part_group` (`NEURO`, `BODY`, `MSK`, `CHEST`, `VASCULAR`, or `OTHER`), and `priority` (`STAT`, `URGENT`, or `ROUTINE`) — together with the `required_subspecialty` a reader must hold for matched studies and a `prelim_required` flag (default false) that, when true, obliges a signed preliminary report before any final. Creation is concurrency-guarded by `expected_hospital_version` as described in §2.7, and it carries two side effects beyond the new row: the hospital's `version` increments by 1, and any existing `ACTIVE` policy sharing the same four-part key transitions `ACTIVE → RETIRED` — the superseded policy's `version` increments, it lands in the terminal `RETIRED` status, and it no longer resolves at route time, leaving exactly one `ACTIVE` policy per key. Policies may be listed by `hospital_id` and `status`.

Studies enter the platform when a `ClientHospitalUser` registers one with the ordering `hospital_id` (which must equal their own `X-User-ID`), an `accession_number`, the `modality`, the `body_part_group`, the read `priority`, and an opaque `patient_ref` carrying no PHI semantics. Registration requires the hospital to be `ACTIVE` (else `ERR_HOSPITAL_NOT_ACTIVE`), and the accession number must be unique per hospital among studies that have not been `CANCELLED`; a duplicate is rejected with `ERR_DUPLICATE_ACCESSION`. At creation the system copies the hospital's `state_code` onto the study as its licensure scope, stamps `received_at` from the logical clock, and computes `due_at` by adding the hospital's configured turnaround minutes for the study's priority to `received_at` — an exact instant at second precision. The study begins in `RECEIVED` status with `routing_policy_id` and `assigned_radiologist_id` null, `excluded_radiologist_ids` empty, `addendum_count` zero, `first_final_signed_at` null, `tat_breached` false, and `breach_minutes` zero.

Routing is performed by `DispatchOps` and moves `RECEIVED → QUEUED`. It resolves the hospital's single `ACTIVE` routing policy matching the study's modality, body-part group, and priority; if none matches, the route is rejected with `ERR_NO_ROUTING_POLICY`. A successful route writes the matched policy's id into the study's `routing_policy_id` and increments the study's `version`. The study list supports reverse-lookup filters on `hospital_id`, `routing_policy_id`, and `assigned_radiologist_id` as well as `status` and `priority`.

### 3.5. Building the Worklist: Assignment and the Auto-Selector

Assignment is the act that commits reading capacity. `DispatchOps` assigns a study in `QUEUED`, `PRELIMINARY_SIGNED`, or `AMENDMENT_PENDING` status — moving it to `ASSIGNED` — by supplying the `study_id`, the OCC field `expected_study_version`, and optionally a `radiologist_id`. The study must have no other `ACTIVE` assignment. The new assignment is created `ACTIVE` with two derived attributes: a `phase` of `PRELIMINARY` when the resolved policy's `prelim_required` is true and no `SIGNED` preliminary report exists yet for the study, and `FINAL` otherwise; and a `reserved_rvu` equal to the study's base RVU. The base RVU depends only on modality: `CT` 1.5, `MR` 2.0, `XR` 0.5, `US` 1.0, `NM` 1.5, and `MG` 1.0, carried at 1 decimal place. When `radiologist_id` is omitted, the system chooses the reader itself and stamps the assignment's `auto_selected` flag true; when supplied, the flag is false and the named radiologist is vetted against the same gates, subject to the gate-(9) carve-out for manual assignment described below. Assignment cascades immediately: the study's `assigned_radiologist_id` is set to the chosen reader, the radiologist's `reserved_rvu` increases by the study's base RVU, `stat_active_count` rises by one when the study is `STAT`, and the study's `version` increments.

The auto-selector filters every radiologist through nine eligibility gates. The candidate must (1) be `ACTIVE`; (2) hold the study's `state_code` among their `license_states`; (3) hold the policy's `required_subspecialty` among their `subspecialties` whenever the study was routed (that is, whenever `routing_policy_id` is non-null); (4) hold an active credential grant for the study's hospital as defined in §3.3; (5) hold an `ACTIVE` coverage shift whose `modalities` include the study's modality; (6) not appear in the study's `excluded_radiologist_ids`; (7) have headroom such that `reserved_rvu` plus the study's base RVU does not exceed `fatigue_cap_rvu` — equality is allowed; (8) for a `STAT` study, have a `stat_active_count` still below `max_concurrent_stat`; and (9) for a `FINAL`-phase assignment where a signed preliminary exists, not be the preliminary signer. Survivors are ranked by utilization ratio — `reserved_rvu` plus the study's base RVU, divided by `fatigue_cap_rvu` — ascending, compared exactly without rounding; ties break first on `stat_active_count` ascending, then on the radiologist's `created_at` ascending, and finally on the radiologist's `id` ascending. An empty candidate pool rejects the assignment with `ERR_NO_ELIGIBLE_RADIOLOGIST` and the study remains `QUEUED`.

Manual assignment evaluates these same gates with one carve-out: gate (9) is an auto-selector filter only, so a manually named FINAL-phase candidate who signed the study's preliminary report is not rejected at assignment time — that same-reader conflict is instead rejected at sign time with `ERR_SAME_READER_CONFLICT`, as §3.6 describes. For every other gate, manual assignment maps the first failing filter to its error in validation-priority order: a candidate who is not `ACTIVE`, or who lacks the routed policy's `required_subspecialty`, rejects with `ERR_NO_ELIGIBLE_RADIOLOGIST`; a licensure gap rejects with `ERR_LICENSURE_GAP`; a missing or inactive credential with `ERR_CREDENTIAL_NOT_ACTIVE`; a reader on the study's exclusion list with `ERR_READER_EXCLUDED_FOR_STUDY`; a lack of modality-matching active shift with `ERR_NO_ACTIVE_SHIFT`; projected utilization strictly beyond the fatigue cap with `ERR_FATIGUE_CAP_EXCEEDED`; and a STAT assignment at the concurrency bound with `ERR_STAT_CONCURRENCY_LIMIT`. Once assigned, only the named radiologist may accept: acceptance requires the assignment `ACTIVE`, the caller's `X-User-ID` equal to the assignment's `radiologist_id`, and the study in `ASSIGNED`; it moves the study to `IN_PROGRESS` and increments both the study's and the assignment's `version`. A radiologist may instead release their own active assignment under the same ownership and state preconditions; release moves the assignment to `RELEASED`, returns the study to `QUEUED` with `assigned_radiologist_id` cleared, appends the releasing radiologist to the study's `excluded_radiologist_ids` so they cannot be picked again for this study, decrements the radiologist's `reserved_rvu` by the study's base RVU, adjusts `stat_active_count` when the study is `STAT`, and increments both resources' `version`. Assignments may be listed filtered by `study_id`, `radiologist_id`, or `status`.

### 3.6. Reading and Signing: Preliminary, Final, and Addendum Reports

With a study `IN_PROGRESS`, the assigned radiologist drafts a report against their assignment by supplying the `assignment_id`, a `report_type` of `PRELIMINARY`, `FINAL`, or `ADDENDUM`, the `findings_text` and `impression_text` narratives, an optional `critical_finding` flag (default false), and an optional `discrepancy_grade`. The draft is created in `DRAFT` status with `study_id` and `radiologist_id` copied from the assignment; the author is always the assignment's radiologist, and the assignment must be `ACTIVE` with its study `IN_PROGRESS`.

Signing is the pivotal act and is restricted to the report's own author (`X-User-ID` equal to the report's `radiologist_id`) with the report still `DRAFT`; the study must still be `IN_PROGRESS` and the report's assignment still `ACTIVE`. What signing means depends on the report type, and each variant drives its own cascade.

Signing a `PRELIMINARY` report is permitted only when the resolved policy's `prelim_required` is true and no signed preliminary already exists for the study; both violations reject with `ERR_PRELIM_NOT_PERMITTED`. On signature the report becomes `SIGNED` with `signed_at` stamped from the logical clock, and it earns provisional credit: 0.8 times the study's base RVU, rounded half-up to 2 decimal places, written to `credited_rvu`. The study moves `IN_PROGRESS → PRELIMINARY_SIGNED`; the assignment completes, releasing its reservation from `reserved_rvu` and adding the credit into `completed_rvu_24h`; and because the policy required a preliminary, this signature is the TAT-relevant one — `tat_breached` and `breach_minutes` are evaluated from the preliminary's `signed_at` against `due_at`.

Signing a `FINAL` report is gated more heavily. No signed final may already exist for the study — one that does rejects with `ERR_INVALID_STATE` — and this duplicate-final check runs first, before the remaining gates. When the resolved policy requires a preliminary, a signed preliminary must already exist, else the sign rejects with `ERR_FINAL_NOT_DUE`. When a signed preliminary exists, the final signer must differ from the preliminary signer — a same-reader final rejects with `ERR_SAME_READER_CONFLICT` — and the payload must carry a `discrepancy_grade`, else `ERR_VALIDATION`; the grade runs 0 (concordant), 1 (minor), 2 (moderate), to 3 (major). On signature the report becomes `SIGNED`, the study moves `IN_PROGRESS → FINAL_SIGNED`, and `first_final_signed_at` is pinned to this signature's `signed_at` — the billing anchor that later addenda never move. The final's credit is the study's base RVU multiplied by one minus the discrepancy penalty for the grade: grades 0 and 1 carry a penalty of 0, grade 2 carries 0.25, and grade 3 carries 0.5; the penalty keys off the grade recorded on the report, so a null grade (the norm when no signed preliminary exists) carries a penalty of 0, while a grade supplied on the draft applies even then. The result is rounded half-up to 2 decimal places. The study's signed preliminary report, if any, transitions `SIGNED → SUPERSEDED` — its provisional credit stands and is not clawed back. The assignment completes with the same reservation-release and credit accumulation as the preliminary path. When the policy did not require a preliminary, this final signature is the TAT-relevant one and breach is evaluated from the final's `signed_at`. Finally, a grade of 2 or 3 on a final signed against an existing signed preliminary automatically opens a discrepancy case in `OPEN` status with `origin` `AUTO`, seeded from the two reports.

Signing an `ADDENDUM` report requires the study's `first_final_signed_at` to be set — an addendum against a study with no signed final rejects with `ERR_ADDENDUM_NOT_PERMITTED` — and the addendum signer, like a final signer, must differ from the preliminary signer under the same `ERR_SAME_READER_CONFLICT` rule. The addendum must be signed from `IN_PROGRESS`, which the study reaches by being re-assigned while `AMENDMENT_PENDING`. An addendum earns no RVU credit: its `credited_rvu` is 0.0. On signature the study returns to `FINAL_SIGNED`, `addendum_count` increases by 1, `first_final_signed_at` is left untouched, and the assignment completes with the usual recomputation of the radiologist's utilization counters.

Breach evaluation follows one rule regardless of which signature is TAT-relevant: the relevant `signed_at` is compared to `due_at`, and `tat_breached` becomes true only when the signature is strictly later than the deadline — signing exactly at `due_at` is on time. When breached, `breach_minutes` is the number of whole minutes of lateness, computed by taking the signed-to-due difference in seconds and discarding any partial minute; when on time, `breach_minutes` is 0. Reports can be listed by `study_id`, `assignment_id`, `radiologist_id`, `report_type`, or `status`.

A study that has reached `FINAL_SIGNED` may be sent back for amendment by its owning `ClientHospitalUser`: the request-addendum action moves `FINAL_SIGNED → AMENDMENT_PENDING` and increments the study's `version`, but it is blocked while any discrepancy case for the study sits in `OPEN`, `PEER_REVIEW`, or `ESCALATED_QI`, rejecting with `ERR_OPEN_DISCREPANCY_EXISTS`. Cancellation is the study's terminal exit: from `RECEIVED`, `QUEUED`, `ASSIGNED`, or `IN_PROGRESS`, the owning `ClientHospitalUser` (or `DispatchOps`) may cancel, moving the study to `CANCELLED`. Cancelling from `ASSIGNED` or `IN_PROGRESS` cascades: the active assignment transitions to `RELEASED`, the study's `assigned_radiologist_id` is cleared, and the radiologist's `reserved_rvu` and `stat_active_count` are recomputed to return the reservation (unlike a radiologist-initiated release, cancellation does not append the radiologist to `excluded_radiologist_ids`). Finalized studies — those in `PRELIMINARY_SIGNED`, `FINAL_SIGNED`, or `AMENDMENT_PENDING` — cannot be cancelled; an attempt against any impermissible state rejects with `ERR_INVALID_STATE`.

### 3.7. Critical Result Communication

A report signed with `critical_finding` true spawns, in the same request, a **critical-result notice** in `PENDING` status referencing the `report_id`, the `study_id`, and the signing `radiologist_id`, and raising that radiologist's `pending_critical_count` by one. This happens identically on preliminary, final, and addendum signatures.

The communication workflow then documents contact with the client hospital. The signing radiologist — and only that radiologist — records the notification, supplying the `notified_party_name`; this moves `PENDING → NOTIFIED` (or `ESCALATED → NOTIFIED` when contact is finally made after an escalation), stamps `notified_at` from the logical clock, and increments the notice's `version`. The client hospital then confirms read-back: a `ClientHospitalUser` whose `X-User-ID` equals the study's `hospital_id` supplies `readback_confirmed_by`, moving `NOTIFIED → READBACK_CONFIRMED` (or `ESCALATED → READBACK_CONFIRMED`) provided `notified_at` has been set; this stamps `readback_at`, decrements the radiologist's `pending_critical_count` by one, and closes the notice terminally.

Escalation is both manual and automatic. `DispatchOps` may escalate any notice in `PENDING` or `NOTIFIED`, moving it to `ESCALATED` with `escalation_count` increased by 1. The clock sweep performs the automatic form: a notice still `PENDING` once the logical clock has passed thirty minutes beyond its `created_at` escalates, and a `NOTIFIED` notice whose read-back is still outstanding (`readback_at` null) once the clock has passed sixty minutes beyond `notified_at` escalates; each sweep escalation likewise raises `escalation_count` by 1 and increments `version`. Notices are listed with filters on `report_id`, `study_id`, `radiologist_id`, and `status`, and are readable by all five roles.

### 3.8. Discrepancy Reconciliation and Quality Review

Discrepancy cases arise two ways. Automatically, a final signature carrying a `discrepancy_grade` of 2 or 3 opens a case as described in §3.6. Manually, a `QaReviewer` may open a case by naming the `prelim_report_id` and `final_report_id`; the named reports must actually be a `PRELIMINARY` and a `FINAL` report respectively and must belong to the same study, else `ERR_VALIDATION`. The case copies its `study_id` from the reports, copies its `grade` from the final report's `discrepancy_grade`, and is stamped with `origin` `MANUAL` (the automatic form carries `AUTO`). Manual creation is rejected with `ERR_OPEN_DISCREPANCY_EXISTS` when a non-terminal case already exists for the same report pair — the same guard that blocks addendum requests while any case on the study remains in `OPEN`, `PEER_REVIEW`, or `ESCALATED_QI`.

A case opens in `OPEN` status. A `QaReviewer` may move `OPEN → PEER_REVIEW` to begin formal review, or — only when the case's `grade` is 1 or 0 (a null `grade`, possible on a manually opened case, also qualifies) — close it outright via `OPEN → NO_ACTION_CLOSED`. From `PEER_REVIEW` the reviewer may escalate to `ESCALATED_QI`, and from either `PEER_REVIEW` or `ESCALATED_QI` the case is reconciled into the terminal `RECONCILED` state by supplying a `reconciliation_note`. Reconciliation enforces segregation of duties: the reconciler's `X-User-ID` must differ from both the preliminary report's `radiologist_id` and the final report's `radiologist_id`, else the request is rejected with `ERR_SELF_RECONCILIATION_FORBIDDEN` (HTTP 403). A successful reconcile records the caller in `reconciled_by` alongside the note. Every case transition increments the case's `version`. Cases are listed with filters on `study_id`, `prelim_report_id`, `final_report_id`, and `status`, and are readable by `PlatformAdmin`, `DispatchOps`, and `QaReviewer`.

### 3.9. Billing Periods, Invoice Generation, and Volume Pricing

Billing is organized into per-hospital **billing periods**. A `PlatformAdmin` opens a period with the `hospital_id`, a `period_start`, and a `period_end`, both `YYYY-MM-DD` dates with `period_end` on or after `period_start` (else `ERR_VALIDATION`); the billable window spans from midnight UTC at the start of `period_start` to midnight UTC at the start of the day after `period_end`. Periods for the same hospital follow inclusive-day semantics: a new period may not share even one calendar day with an existing period of that hospital in `OPEN`, `CLOSED`, or `INVOICED` status, else `ERR_PERIOD_OVERLAP`. A period opens `OPEN`; closing moves `OPEN → CLOSED`. A closed period may be reopened within a grace window: reopening moves `CLOSED → OPEN` provided the current logical day is on or before seven days after `period_end`, counting inclusively — a period ending 2026-05-31 may be reopened through 2026-06-07 and rejects on 2026-06-08 with `ERR_REOPEN_WINDOW_EXPIRED`. Each transition increments the period's `version`.

Invoice generation is available from `CLOSED` (first generation) and from `INVOICED` (regeneration), moves the period to `INVOICED`, and is concurrency-guarded by `expected_billing_period_version` per §2.7. Generation pins the hospital's current `pricing_mode` into the invoice's `pricing_mode_snapshot` at generation time and builds the **billable set**: the hospital's studies whose `first_final_signed_at` falls inside the billable window and whose status is `FINAL_SIGNED` or `AMENDMENT_PENDING`. Billable studies are ordered by `first_final_signed_at` ascending, ties broken by `created_at` ascending and then by the study's `id` ascending, and numbered from 1; `billable_study_count` records how many were found.

Volume pricing uses three tiers. Units 1 through 1000 bill at 901 cents each, units 1001 through 5000 at 801 cents, and units 5001 and beyond at 701 cents. The two pricing variants diverge here: under `MARGINAL`, each unit is billed at the rate of the tier containing its own index; under `FLAT_TIER`, every unit is billed at the single rate of the highest tier reached by `billable_study_count`, so identical volume yields a different total under the two variants. Independently of tier, each unit is classified by hour: a study whose `received_at` wall-clock UTC time-of-day falls within the after-hours window — at or after 22:00 and before 07:00 — is an after-hours unit and bills at one and a half times its tier rate. Rounding is pinned and order-sensitive: each after-hours unit's price is rounded half-up to whole cents individually, before any aggregation, and no other rounding occurs anywhere in invoice composition. To make the order concrete, three after-hours tier-1 units bill as three times the half-up rounding of 901 times 1.5 — three times 1352, totalling 4056 cents; summing the unrounded products first (4054.5 cents) and rounding once to 4055 is a forbidden interpretation.

Units are then aggregated into `line_items`, one line per combination of `hour_class` (`REGULAR` or `AFTER_HOURS`) and `tier_index`, each line carrying its `units`, the per-unit `rate_cents`, and the line `amount_cents` equal to units times unit price; regular-hour units need no rounding since tier rates are already whole cents. Lines are emitted ordered by `hour_class` (`AFTER_HOURS` before `REGULAR`) and then by `tier_index` ascending. On top of the lines, the invoice adds a critical finding add-on: 250 cents per billable study whose signed final report had `critical_finding` true, accumulated in `critical_addon_cents`. The invoice's `gross_cents` is the sum of all line amounts plus the critical add-on. Penalty credits then give money back for lateness: `penalty_credits_cents` sums, over every breached billable study, the lesser of that study's `breach_minutes` multiplied by the hospital's `penalty_per_breach_minute_cents` and the hospital's `breach_penalty_cap_cents` — the cap applies per study. The invoice's `total_cents` is `gross_cents` minus `penalty_credits_cents`, floored at zero so a heavily penalized period never bills negative.

A generated invoice is born `CURRENT` with its `billing_period_id` set and its `hospital_id` denormalized from the period. Regenerating an already-`INVOICED` period supersedes the previous invoice: the prior `CURRENT` invoice transitions to the terminal `VOID` state with its `version` incremented, the fresh invoice becomes the `CURRENT` one, and the period's `version` increments. Invoices are readable by `PlatformAdmin` and the owning `ClientHospitalUser`, and the invoice list filters by `billing_period_id`, `hospital_id`, and `status`; periods list by `hospital_id` and `status`.

For fixture and test-driving purposes, a `PlatformAdmin` may also seed a hospital with studies that are already finalized: the seeding capability takes the `hospital_id`, a `count`, a `received_at`, and a `final_signed_at`, with optional `modality` (default `CT`), `priority` (default `ROUTINE`), `body_part_group` (default `OTHER`), and `critical_finding` (default false). The hospital must exist but need not be `ACTIVE`, and a `count` that is not a non-negative integer is rejected with `ERR_VALIDATION`. Seeding creates that many studies directly in `FINAL_SIGNED` status — each with `due_at`, `tat_breached`, and `breach_minutes` computed by the normal rules — returning `created_count` and the `study_ids`. When `critical_finding` is true, each seeded study also gets a `SIGNED` `FINAL` report carrying the flag (with null `radiologist_id` and `assignment_id`) so that the invoice critical-finding add-on applies to it. The seeded `received_at` time-of-day is what drives after-hours classification for these studies on later invoices.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, trigger a state transition, or advance the logical clock return `200 OK`. Request and response payloads for every endpoint are as narrated in §2 and §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/telerad/_clock/set_current_utc` | Advance the logical clock; runs shift, grant, and notice sweeps | PlatformAdmin |
| POST | `/telerad/_seed/finalized-studies` | Seed finalized studies for a hospital (test fixture) | PlatformAdmin |
| POST | `/telerad/hospitals` | Register a client hospital | PlatformAdmin |
| GET | `/telerad/hospitals/{id}` | Read a hospital | PlatformAdmin, DispatchOps, ClientHospitalUser |
| GET | `/telerad/hospitals` | List hospitals | PlatformAdmin, DispatchOps |
| POST | `/telerad/hospitals/{id}/activate` | Activate (or reactivate) a hospital | PlatformAdmin |
| POST | `/telerad/hospitals/{id}/suspend` | Suspend a hospital | PlatformAdmin |
| POST | `/telerad/radiologists` | Onboard a radiologist | PlatformAdmin |
| GET | `/telerad/radiologists/{id}` | Read a radiologist incl. computed utilization fields | PlatformAdmin, DispatchOps, Radiologist, QaReviewer |
| GET | `/telerad/radiologists` | List radiologists | PlatformAdmin, DispatchOps, QaReviewer |
| PATCH | `/telerad/radiologists/{id}` | Update status, caps, or credentials | PlatformAdmin |
| POST | `/telerad/shifts` | Schedule a coverage shift | PlatformAdmin |
| GET | `/telerad/shifts/{id}` | Read a shift | PlatformAdmin, DispatchOps, Radiologist |
| GET | `/telerad/shifts` | List shifts | PlatformAdmin, DispatchOps, Radiologist |
| POST | `/telerad/shifts/{id}/cancel` | Cancel a scheduled shift | PlatformAdmin |
| POST | `/telerad/routing-policies` | Create a routing rule (OCC on hospital); retires same-key active policy | PlatformAdmin |
| GET | `/telerad/routing-policies/{id}` | Read a routing policy | PlatformAdmin, DispatchOps |
| GET | `/telerad/routing-policies` | List routing policies | PlatformAdmin, DispatchOps |
| POST | `/telerad/credential-grants` | Apply for privileges at a hospital | PlatformAdmin |
| GET | `/telerad/credential-grants/{id}` | Read a credential grant | PlatformAdmin, DispatchOps, Radiologist |
| GET | `/telerad/credential-grants` | List credential grants | PlatformAdmin, DispatchOps, Radiologist |
| POST | `/telerad/credential-grants/{id}/grant` | Grant a pending application | PlatformAdmin |
| POST | `/telerad/credential-grants/{id}/suspend` | Suspend a granted credential | PlatformAdmin |
| POST | `/telerad/credential-grants/{id}/reinstate` | Reinstate a suspended credential | PlatformAdmin |
| POST | `/telerad/credential-grants/{id}/revoke` | Revoke a granted credential | PlatformAdmin |
| POST | `/telerad/credential-grants/{id}/renew` | Renew an expired grant with a new validity window | PlatformAdmin |
| POST | `/telerad/studies` | Register an inbound study | ClientHospitalUser |
| GET | `/telerad/studies/{id}` | Read a study | PlatformAdmin, DispatchOps, Radiologist, ClientHospitalUser, QaReviewer |
| GET | `/telerad/studies` | List studies | PlatformAdmin, DispatchOps, Radiologist, ClientHospitalUser, QaReviewer |
| POST | `/telerad/studies/{id}/route` | Route a received study to its policy queue | DispatchOps |
| POST | `/telerad/studies/{id}/cancel` | Cancel a non-finalized study | ClientHospitalUser, DispatchOps |
| POST | `/telerad/studies/{id}/request-addendum` | Request an addendum on a finalized study | ClientHospitalUser |
| POST | `/telerad/assignments` | Assign a study (manual or auto-selected; OCC on study) | DispatchOps |
| GET | `/telerad/assignments/{id}` | Read an assignment | PlatformAdmin, DispatchOps, Radiologist, QaReviewer |
| GET | `/telerad/assignments` | List assignments | PlatformAdmin, DispatchOps, Radiologist, QaReviewer |
| POST | `/telerad/assignments/{id}/accept` | Radiologist accepts own assignment | Radiologist |
| POST | `/telerad/assignments/{id}/release` | Radiologist releases own assignment | Radiologist |
| POST | `/telerad/reports` | Create a draft report on an active assignment | Radiologist |
| GET | `/telerad/reports/{id}` | Read a report | PlatformAdmin, DispatchOps, Radiologist, QaReviewer, ClientHospitalUser |
| GET | `/telerad/reports` | List reports | PlatformAdmin, DispatchOps, Radiologist, QaReviewer, ClientHospitalUser |
| POST | `/telerad/reports/{id}/sign` | Sign a draft report | Radiologist |
| POST | `/telerad/discrepancy-cases` | Manually open a discrepancy case | QaReviewer |
| GET | `/telerad/discrepancy-cases/{id}` | Read a discrepancy case | PlatformAdmin, DispatchOps, QaReviewer |
| GET | `/telerad/discrepancy-cases` | List discrepancy cases | PlatformAdmin, DispatchOps, QaReviewer |
| POST | `/telerad/discrepancy-cases/{id}/open-peer-review` | Open peer review on a case | QaReviewer |
| POST | `/telerad/discrepancy-cases/{id}/close-no-action` | Close a low-grade case with no action | QaReviewer |
| POST | `/telerad/discrepancy-cases/{id}/escalate` | Escalate a case to QI | QaReviewer |
| POST | `/telerad/discrepancy-cases/{id}/reconcile` | Reconcile a case under review | QaReviewer |
| GET | `/telerad/critical-notices/{id}` | Read a critical-result notice | PlatformAdmin, DispatchOps, Radiologist, ClientHospitalUser, QaReviewer |
| GET | `/telerad/critical-notices` | List critical-result notices | PlatformAdmin, DispatchOps, Radiologist, ClientHospitalUser, QaReviewer |
| POST | `/telerad/critical-notices/{id}/record-notification` | Record notification of the client | Radiologist |
| POST | `/telerad/critical-notices/{id}/confirm-readback` | Confirm read-back of a critical result | ClientHospitalUser |
| POST | `/telerad/critical-notices/{id}/escalate` | Manually escalate a notice | DispatchOps |
| POST | `/telerad/billing-periods` | Open a billing period | PlatformAdmin |
| GET | `/telerad/billing-periods/{id}` | Read a billing period | PlatformAdmin, ClientHospitalUser |
| GET | `/telerad/billing-periods` | List billing periods | PlatformAdmin, ClientHospitalUser |
| POST | `/telerad/billing-periods/{id}/close` | Close a billing period | PlatformAdmin |
| POST | `/telerad/billing-periods/{id}/reopen` | Reopen a closed period within the grace window | PlatformAdmin |
| POST | `/telerad/billing-periods/{id}/generate-invoice` | Generate (or regenerate) the period's invoice (OCC on period) | PlatformAdmin |
| GET | `/telerad/invoices/{id}` | Read an invoice incl. computed lines and totals | PlatformAdmin, ClientHospitalUser |
| GET | `/telerad/invoices` | List invoices | PlatformAdmin, ClientHospitalUser |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_HOSPITAL_NOT_FOUND` | 404 |
| `ERR_RADIOLOGIST_NOT_FOUND` | 404 |
| `ERR_SHIFT_NOT_FOUND` | 404 |
| `ERR_POLICY_NOT_FOUND` | 404 |
| `ERR_GRANT_NOT_FOUND` | 404 |
| `ERR_STUDY_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_NOTICE_NOT_FOUND` | 404 |
| `ERR_BILLING_PERIOD_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_HOSPITAL_NOT_ACTIVE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_ACCESSION` | 409 |
| `ERR_NO_ROUTING_POLICY` | 422 |
| `ERR_LICENSURE_GAP` | 422 |
| `ERR_CREDENTIAL_NOT_ACTIVE` | 422 |
| `ERR_GRANT_TYPE_MISMATCH` | 422 |
| `ERR_SAME_READER_CONFLICT` | 422 |
| `ERR_PRELIM_NOT_PERMITTED` | 422 |
| `ERR_FINAL_NOT_DUE` | 422 |
| `ERR_ADDENDUM_NOT_PERMITTED` | 422 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_GRANT_OVERLAP` | 409 |
| `ERR_PERIOD_OVERLAP` | 409 |
| `ERR_NO_ACTIVE_SHIFT` | 422 |
| `ERR_READER_EXCLUDED_FOR_STUDY` | 422 |
| `ERR_OPEN_DISCREPANCY_EXISTS` | 409 |
| `ERR_REOPEN_WINDOW_EXPIRED` | 422 |
| `ERR_FATIGUE_CAP_EXCEEDED` | 422 |
| `ERR_STAT_CONCURRENCY_LIMIT` | 422 |
| `ERR_NO_ELIGIBLE_RADIOLOGIST` | 422 |
| `ERR_SELF_RECONCILIATION_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INTERNAL` | 500 |
