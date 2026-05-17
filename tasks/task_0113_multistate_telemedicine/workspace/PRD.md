# Multistate Telemedicine API — Product Requirements Document

## 1. Introduction

Telemedicine practice has outgrown the regulatory model that produced the medical-licensure system: a physician sitting in one state may legitimately treat a patient sitting in another, but the prescription pad, the controlled-substance registry, and the malpractice envelope all remain anchored to the state where care is *rendered* — that is, where the patient is physically located at the moment of the consult. The Multistate Telemedicine platform addresses this mismatch by serving as the system of record for cross-state practice: it maintains each physician's portfolio of state medical licenses (both full single-state licenses and Interstate Medical Licensure Compact expedited licenses), determines which license satisfies a given patient's present state, governs DEA-compliant electronic prescribing, and routes consult billing to either an insurance payer or a self-pay invoice depending on what the originating consult declared.

The platform's hardest requirement is **continuous compliance**: a license that was valid when a consult was routed may be revoked before the physician completes treatment, and the platform must propagate that revocation immediately — unrouting the affected consult, voiding any draft prescriptions that hang off it, and refusing any further state transitions that would rely on the now-invalid license. Equally, controlled-substance prescriptions carry their own time windows, follow-up obligations, and refill rules that ripple into how soon the patient must be seen again. This API is designed as the immediate-consistency arbiter of those cross-cutting concerns, with an append-only audit trail captured at every consequential transition so that downstream compliance review has a faithful event-by-event record.

The audience for this document is the engineering team implementing the platform's REST surface. The discussion proceeds from cross-cutting principles (authentication, response shape, precision, concurrency) into business workflows (registration, consult lifecycle, prescribing, billing, follow-up) and concludes with the catalog of endpoints and error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request the platform accepts — with the deliberate exception of the two operator-driven testing utilities (clock advancement and the nightly sweep, both detailed in §3.7) — must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming one of the four roles below. A request that omits either header is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not authorized for the endpoint in question is rejected with `ERR_FORBIDDEN`. The four roles are spelled, exactly:

- `PlatformAdmin` — the operator who registers physicians and patients, files licenses, performs license revocations, and drives the simulated clock and the nightly sweep. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it in audit events (where the actor for a platform-admin-triggered transition is the value passed in `X-User-ID`) but does not compare it to any entity's `id`.
- `ComplianceOfficer` — routes consults to physicians, declines or unroutes consults before treatment begins, closes consults once billing and follow-up have terminated, appeals denied insurance claims, marks transmitted prescriptions as dispensed, marks self-pay invoices paid, and cancels scheduled follow-ups. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it in audit events but does not compare it to any entity's `id`.
- `Physician` — starts and completes consults assigned to them, drafts and edits prescriptions, issues, transmits, and voids them, and completes scheduled follow-ups. When `X-User-Role` is `Physician`, `X-User-ID` is the `id` of the acting `Physician`. Ownership checks on any resource that references a `Physician` — most importantly the `physician_id` on a `Consult` and the `prescribing_physician_id` on a `Prescription` — compare the resource's foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`.
- `Payer` — the insurance counterparty: approves, denies, and marks paid an `InsuranceClaim` they are responsible for. When `X-User-Role` is `Payer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it in the audit event but does not compare it to any entity's `id`.

Segregation of duties is enforced at the role level: a `Physician` cannot route, decline, close, or appeal a consult, cannot mark a prescription dispensed, and cannot edit a `Patient` record. A `ComplianceOfficer` cannot start, complete, prescribe, or issue prescriptions. The endpoint table in §4 enumerates the authorized roles per endpoint; mismatches surface as `ERR_FORBIDDEN`.

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

Every list endpoint accepts two optional query parameters: `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, must be at least 1, and must not exceed 100; the `offset` parameter defaults to 0 when omitted and must be a non-negative integer. Any request that violates these bounds is rejected with `ERR_PAGINATION_INVALID`. Results are always returned sorted by `created_at` in ascending order — that is, the oldest record first — and the response's `meta` block echoes `limit`, `offset`, the unfiltered `total_count` matching the query, and a boolean `has_more` indicating whether further pages remain past the current window.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persistable resource carries a server-minted `id` field that is a plain UUID string with no type prefix; clients never supply it. Most resources additionally carry three system-managed timestamps and version columns: `created_at` and `updated_at`, both ISO 8601 UTC strings with three fractional digits, and `version`, a non-negative integer that starts at 1 on creation and increments by exactly 1 on every server-side mutation of that row (including state transitions and cascade-induced mutations). The one exception is `AuditEvent` rows, which are append-only: they carry an `id` and a `created_at` but have **no** `updated_at` field and **no** `version` field, because they are never mutated after they are written. All other entities — `Physician`, `StateLicense`, `Patient`, `Consult`, `Prescription`, `InsuranceClaim`, `SelfPayInvoice`, and `FollowUp` — carry the full triplet of `created_at`, `updated_at`, and `version`.

### 2.5. Optimistic Concurrency Control

Any endpoint that mutates a resource accepts an optional `version` field in its request body. When `version` is supplied and it does not equal the resource's current `version`, the request is rejected with `ERR_VERSION_CONFLICT`. When `version` is omitted, the check is skipped and the mutation proceeds against whatever version the resource currently holds — callers who care about lost-update protection are expected to read first and supply the version they read. The version check sits at the priority appropriate for an OCC check and runs after authentication, authorization, existence, and state checks, but before business-rule validation that would invent new error codes for the loser of a race. The contract for racing operations on the same resource is otherwise that **exactly one wins**: two simultaneous attempts to route the same `REQUESTED` consult serialize so that the first succeeds and the second receives `ERR_INVALID_STATE` because the consult is no longer `REQUESTED`; two simultaneous attempts to issue the same `DRAFT` prescription serialize so that the first succeeds and the second sees `ERR_INVALID_STATE`; two simultaneous attempts to create an `InsuranceClaim` for the same `Consult` collide on the uniqueness constraint over `consult_id` and the loser receives `ERR_CLAIM_ALREADY_EXISTS`; two simultaneous edits to the same `DRAFT` prescription where both callers send a `version` collide on OCC and the loser receives `ERR_VERSION_CONFLICT`.

### 2.6. Validation Priority

When multiple validations could fire on the same request, they are evaluated in a fixed total order so that the surfaced error is deterministic and tests can assert it. The order is, top-down: authentication (missing `X-User-ID` or `X-User-Role` → `ERR_UNAUTHENTICATED`), authorization (role not allowed → `ERR_FORBIDDEN`), existence of all path-referenced resources, evaluated left-to-right through the URL hierarchy (any miss → `ERR_NOT_FOUND`), state-machine permissibility for the target resource (→ `ERR_INVALID_STATE`), then the family of business-referential and business-safety checks. Within the business family, on a prescription that fails several conditions at once, physician-mismatch (→ `ERR_PHYSICIAN_MISMATCH`) is evaluated before licensure (→ `ERR_NO_VALID_LICENSE`), then DEA prerequisite (→ `ERR_DEA_REQUIREMENTS_NOT_MET`), then the Schedule II refills hard rule (→ `ERR_SCHEDULE_II_REFILLS_FORBIDDEN`), then the compliance-score gate (→ `ERR_COMPLIANCE_SCORE_TOO_LOW`); on consult creation, insurance enrolment (→ `ERR_INSURANCE_NOT_ENROLLED`) is checked before the per-prescription range checks (→ `ERR_RX_FIELD_OUT_OF_RANGE`), which themselves precede the temporal "patient must not already have an active consult" check (→ `ERR_PATIENT_HAS_ACTIVE_CONSULT`). The follow-up window check (→ `ERR_FOLLOWUP_WINDOW_EMPTY`), the close-time billing-terminal check (→ `ERR_BILLING_NOT_TERMINAL`), the license overlap check (→ `ERR_LICENSE_PERIOD_OVERLAP`), and the OCC version check (→ `ERR_VERSION_CONFLICT`) all sit later than the structural and safety layers. Pagination input validity (→ `ERR_PAGINATION_INVALID`) is checked on every list endpoint.

### 2.7. Cascading Mutations and Versioning of Affected Rows

When a single platform action induces mutations on multiple rows — license revocation is the canonical example — every affected row has its `updated_at` refreshed and its `version` incremented, exactly as if the mutation had been a direct edit. The append-only `AuditEvent` rows generated as part of the cascade are new rows and have no version of their own. The cascade is depth-3 at its deepest: the revoke of a `StateLicense` is link one; the forced unroute of any non-terminal `Consult` whose `physician_id` and `present_state_code` match the revoked license is link two (with `physician_id` cleared to null and `routing_basis` cleared to null on each such consult); the auto-void of every `DRAFT` `Prescription` under each affected consult is link three, with `void_reason` set to `'LICENSE_REVOKED'` and an `AuditEvent` of type `RX_VOIDED` appended per voided prescription. The platform also emits an `AuditEvent` of type `LICENSE_REVOKED` for the originating license itself. All three links commit immediately and atomically within the same request: there is no eventual-consistency window.

### 2.8. Monetary Precision and Rounding

All monetary fields are integers measured in cents. Intermediate ratios — most importantly the coinsurance computation in the insurance billing waterfall and the courtesy-discount computation in the self-pay billing variant — are computed in floating point and rounded **half-up** to the nearest cent after each step of the waterfall, in the order specified by the calculation. There is no other rounding mode; banker's rounding is not used.

### 2.9. The Simulated Clock and Time-Gated States

For reproducibility, the platform's notion of "now" is a simulated clock that advances only when an operator calls the clock-advancement utility. Two states are reachable only after the clock has been moved forward past the relevant boundary: a `StateLicense` projects to `EXPIRED` once the clock crosses `expires_at`, and a `FollowUp` projects to `MISSED` once the clock crosses `due_by` and the nightly sweep is run. Note that license status is a **projection** computed at read time and during state-machine preconditions; it is not stored as a stable column. The projection rule is closed-form: if an `AuditEvent` of type `LICENSE_REVOKED` exists whose `subject_id` is the license's `id`, the license projects to `REVOKED`; else if the simulated clock's "now" is at or after the license's `expires_at`, it projects to `EXPIRED`; else it projects to `ACTIVE`. There is no reinstatement path, so the projection has no replay loop. License-status comparisons against `expires_at` use UTC seconds.

### 2.10. Append-Only Audit Trail

Every consequential transition appends an `AuditEvent` row, capturing `event_type` (one of `CONSULT_ROUTED`, `RX_ISSUED`, `RX_VOIDED`, `CLAIM_PAID`, `LICENSE_REVOKED`, `COMPLIANCE_FAILURE`, `CLOCK_ADVANCED`), `subject_entity` (the name of the entity the event concerns), `subject_id` (the entity's `id`), `actor_role` (the role string that triggered the event, or the literal `'system'` for automatic cascade transitions and for sweep-driven follow-up flips), and `payload_json` (a free-form JSON snapshot of relevant context captured at event time). Audit events are write-once and never edited or deleted; the audit list endpoint returns them in the standard chronological order and filters via `event_type`, `subject_entity`, and `subject_id` query parameters.

## 3. Business Logic & Workflows

### 3.1. Registering Physicians and Their Licensure Portfolios

A `PlatformAdmin` registers a physician by submitting a payload containing the physician's `full_name`, their 10-digit `npi_number` (which must match the regular expression for ten consecutive digits and be unique across all physicians on the platform), the boolean `imlc_compact_member` flag indicating whether the physician holds an Interstate Medical Licensure Compact Letter of Qualification, the two-letter US state code `imlc_home_state` of the physician's IMLC State-of-Principal-License when `imlc_compact_member` is true (otherwise null), and an optional `dea_number` for controlled-substance authority (matching the pattern of two uppercase letters followed by seven digits, unique across physicians when present). A new physician is created in `ACTIVE` status by default; the alternative is `SUSPENDED`. The `imlc_compact_member` flag defaults to `false` and `dea_number` defaults to null when omitted.

Each physician's right to render care in a given state is represented by one or more `StateLicense` rows under that physician. A `StateLicense` is registered by submitting a `state_code` (two uppercase letters matching the US-state pattern), the issuing board's `license_number`, the `license_type` (either `FULL` for a traditional single-state license or `IMLC_EXPEDITED` for one issued through the Compact), `issued_at`, and `expires_at`. The `expires_at` must be strictly greater than `issued_at`. Multiple licenses for the same physician in the same state are permitted only when their active intervals do not collide: each license's active interval is the half-open range from `issued_at` (inclusive) to `expires_at` (exclusive), and two licenses for the same `(physician_id, state_code)` are considered to overlap when the start of one is strictly before the end of the other and vice versa. Back-to-back licenses — where the first ends at exactly the same instant the second begins — are explicitly permitted; an attempted registration that overlaps is rejected with `ERR_LICENSE_PERIOD_OVERLAP`.

License status is not a stable stored value but a per-read projection (see §2.9): an `ACTIVE` license becomes `EXPIRED` the moment the simulated clock reaches its `expires_at` boundary, and becomes `REVOKED` the moment a platform admin revokes it. Revocation is a depth-3 cascade and is described in §3.6.

### 3.2. Patient Registration and the Present-State Distinction

A `PlatformAdmin` registers a patient by submitting `full_name`, `date_of_birth`, the patient's two-letter `home_state_code`, and optionally a `present_state_code` declaring the patient's physical location for an immediate consult; when `present_state_code` is omitted at registration, the platform treats `home_state_code` as the implicit present state. Patients enrolled with an insurance carrier additionally supply `insurance_payer_id`, `insurance_member_id`, the remaining annual deductible balance in cents (`insurance_deductible_remaining_cents`), a flat copay amount in cents (`insurance_copay_cents`), and a coinsurance percentage stored as basis points (`insurance_coinsurance_bps`, where `2000` means twenty percent, with the constraint that the value is at least 0 and at most 10000). Absent `insurance_payer_id` means the patient is self-pay only; if `insurance_payer_id` is present, `insurance_member_id` must also be supplied. Deductible, copay, and coinsurance default to 0 when not provided.

A patient's mutable fields — most notably `present_state_code`, the three insurance-economics fields, and `version` for optimistic concurrency — can be updated subsequently by a `PlatformAdmin`. Crucially, a patient's `present_state_code` is **read at consult creation time and snapshotted onto the consult**; later edits to the patient record do not retroactively change a consult's `present_state_code`. The same snapshot principle applies to the three insurance-economics fields, which are read at the moment a consult completes and embedded into the resulting `InsuranceClaim` — a later patient update does not retroactively change the billing arithmetic of a completed consult.

### 3.3. Consult Creation and Compliance Routing

A `ComplianceOfficer` opens a consult by supplying the `patient_id`, an optional `present_state_code` override (which falls back to the patient's `home_state_code` when both this field and the patient's stored `present_state_code` are absent), the `billing_mode` (either `INSURANCE` or `SELF_PAY`), the `visit_tier` (`BRIEF`, `STANDARD`, or `EXTENDED`), and a `requires_followup` boolean defaulting to false that captures the clinician-asserted intent for a follow-up at completion time. The consult is created in `REQUESTED` status with `physician_id` set to null and `routing_basis` set to null; these are filled in only when compliance routing succeeds.

Three guardrails fire at creation. First, if `billing_mode` is `INSURANCE`, the patient's record must already contain both `insurance_payer_id` and `insurance_member_id`; if either is missing, the consult creation is rejected with `ERR_INSURANCE_NOT_ENROLLED`. Second, the patient must not currently own another consult in a non-terminal status — meaning any of `REQUESTED`, `ROUTED`, `IN_PROGRESS`, or `COMPLETED` — and a violation surfaces as `ERR_PATIENT_HAS_ACTIVE_CONSULT`. The two terminal states `CLOSED` and `DECLINED` do not block a new consult. Third, all pagination and field-shape requirements still apply.

Compliance routing is the act of binding a `REQUESTED` consult to a specific physician. The compliance officer supplies a `physician_id` and an optional `version`, and the platform searches that physician's licensure portfolio for a `StateLicense` whose `state_code` matches the consult's `present_state_code`, whose projected status is `ACTIVE`, and whose `license_type` is either `FULL` or `IMLC_EXPEDITED`. If no such license exists the route is rejected with `ERR_NO_VALID_LICENSE`. If one exists, the consult's `physician_id` is set, `routing_basis` is set to that matched license's `license_type` (so `FULL_LICENSE` or `IMLC_EXPEDITED`), the consult advances from `REQUESTED` to `ROUTED`, and an `AuditEvent` of type `CONSULT_ROUTED` is appended. The chosen physician must additionally be in `ACTIVE` status (a `SUSPENDED` physician fails the routing precondition). When two compliance officers race to route the same consult, the first request wins and the second sees `ERR_INVALID_STATE` because the consult is no longer `REQUESTED`. Compliance may also decline a `REQUESTED` consult outright, advancing it to `DECLINED` (terminal) without setting `physician_id`.

A consult in `ROUTED` may be reverted back to `REQUESTED` by compliance before treatment begins; the unroute clears `physician_id` and `routing_basis` to null and allows reassignment to another physician. The unroute is permitted **only** when no `Prescription` row yet exists under the consult; if even a single prescription has been drafted, the unroute is refused (because clearing the routed physician would orphan the prescription). Both the route and the unroute accept an optional `version`; mismatch yields `ERR_VERSION_CONFLICT`.

### 3.4. The Treatment Phase: Drafting, Issuing, Transmitting, and Voiding Prescriptions

Once a consult is `ROUTED`, the assigned physician advances it to `IN_PROGRESS` by starting the consult. The platform re-checks at start time that the previously matched `StateLicense` is still `ACTIVE` against the current clock; this prevents a physician from beginning treatment under a license that has expired between routing and start. Only the assigned physician — whose `id` must equal the consult's `physician_id` — may issue this start command.

During `IN_PROGRESS`, the physician drafts prescriptions, each carried under the consult by `consult_id`. A draft prescription specifies `drug_name`, `dea_schedule` (one of `NONE`, `II`, `III`, `IV`, `V` — values introduced unquoted in narrative for legibility but stored as those exact strings), `days_supply`, an optional `refills` count defaulting to 0, and an optional `epcs_two_factor_token` (the EPCS two-factor authentication token presented when issuing controlled substances). The `prescribing_physician_id` on every prescription must equal the owning consult's `physician_id`; a mismatch — even via PATCH — is rejected with `ERR_PHYSICIAN_MISMATCH`. The `days_supply` must lie between 1 and 90 inclusive, and `refills` must lie between 0 and 11 inclusive; a value outside either range is rejected with `ERR_RX_FIELD_OUT_OF_RANGE`. Drafts may be edited in place — a self-loop on `DRAFT` — to correct any of `drug_name`, `dea_schedule`, `days_supply`, `refills`, or `epcs_two_factor_token`; each edit increments `version`, and the same OCC mechanism applies.

Issuing a draft prescription moves it from `DRAFT` to `ISSUED` and is by far the platform's most heavily gated transition. Five gates fire in priority order. First, the issuing physician must be the one whose `id` equals `prescribing_physician_id`, and the owning consult must be in `IN_PROGRESS` — a draft cannot be issued from a `ROUTED` or `COMPLETED` consult. Second, if `dea_schedule` is anything other than `NONE`, the issuing physician's `dea_number` must be on file and the prescription must carry an `epcs_two_factor_token`; absence of either is `ERR_DEA_REQUIREMENTS_NOT_MET`. Third, when `dea_schedule` is `II`, `refills` must be exactly zero — a hard rule from DEA Schedule II policy; any positive refill count is `ERR_SCHEDULE_II_REFILLS_FORBIDDEN`. Fourth, the matched `StateLicense` for the consult's `present_state_code` must still project to `ACTIVE` at issue time; an expired or revoked license blocks issuance. Fifth, a server-computed compliance score (see §3.5) must be at least 80 out of 100; below threshold is `ERR_COMPLIANCE_SCORE_TOO_LOW`. An `AuditEvent` of type `RX_ISSUED` is appended on success. Two simultaneous issuance attempts on the same draft serialize: one wins, the other sees `ERR_INVALID_STATE`.

After issuance, the prescribing physician transmits the prescription to the pharmacy (advancing `ISSUED` to `TRANSMITTED`); a `ComplianceOfficer` later marks it dispensed (advancing `TRANSMITTED` to `DISPENSED`, the terminal happy-path state). Voiding is available from any of `DRAFT`, `ISSUED`, or `TRANSMITTED` and is performed by the prescribing physician with a `void_reason` supplied; the prescription advances to `VOIDED` (the other terminal state) with `void_reason` recorded, and an `AuditEvent` of type `RX_VOIDED` is appended. A draft prescription may also be auto-voided by the system as the third link of the license-revocation cascade described in §3.6, in which case `void_reason` is set to the literal string `'LICENSE_REVOKED'` and the appended audit event lists `'system'` as the actor.

### 3.5. The Prescription Compliance Score

Issuance gate five is a single-prescription compliance score, an integer in the closed interval from 0 to 100 computed from the prescription's own fields, the matched license, and the physician's DEA situation. The score is the sum of four legs.

The first leg awards 40 points when the consult's `routing_basis` is `FULL_LICENSE`, 30 points when it is `IMLC_EXPEDITED`, and 0 points otherwise.

The second leg awards 30 points when `dea_schedule` is `NONE`, and 30 points when `dea_schedule` is anything other than `NONE` *and* the issuing physician's `dea_number` is present *and* the prescription's `epcs_two_factor_token` is present; in every other configuration this leg awards 0 points.

The third leg is the refill-compliance leg and is non-linear by schedule. When `dea_schedule` is `II` and `refills` is exactly zero, this leg awards 20 points; when `dea_schedule` is `II` and `refills` is greater than zero, it awards 0 points (which is also independently disqualifying via the hard Schedule II rule above). When `dea_schedule` is `III` or `IV` and `refills` is at most 5, it awards 20 points; when `dea_schedule` is `III` or `IV` and `refills` is greater than 5, it awards 10 points. When `dea_schedule` is `V` or `NONE`, it awards 20 points.

The fourth leg is the days-supply leg: 10 points when `days_supply` is at most 30, 5 points when `days_supply` is greater than 30 but at most 60, and 0 points when `days_supply` is greater than 60.

The sum across the four legs is the prescription's score. Issuance requires the score to be at least 80; below threshold is `ERR_COMPLIANCE_SCORE_TOO_LOW`.

A read-only aggregate view of the score is also exposed at the physician level, accessible via a capability that returns the average score across that physician's prescriptions whose current status is `ISSUED`, `TRANSMITTED`, or `DISPENSED` (drafts and voided prescriptions are excluded from the average). The aggregate is rounded half-up to one decimal place. The aggregate is observational only — no threshold is enforced on it — and when ranking multiple physicians by this metric, ties are broken by oldest `created_at` first.

### 3.6. License Revocation: The Depth-Three Cascade

When a `PlatformAdmin` revokes a `StateLicense`, three immediate effects unfold within the same request. Link one is the revocation itself: an `AuditEvent` of type `LICENSE_REVOKED` is appended with `subject_id` equal to the license's `id`, and from that moment any read of the license — including state-machine precondition checks — projects its status as `REVOKED`.

Link two scans every consult in `REQUESTED`, `ROUTED`, or `IN_PROGRESS` status whose `physician_id` equals the revoked license's `physician_id` and whose `present_state_code` equals the revoked license's `state_code`. (In practice only consults in `ROUTED` or `IN_PROGRESS` can match this physician/state pair, because `REQUESTED` consults have null `physician_id`; the system transition lives on the `ROUTED → REQUESTED` and `IN_PROGRESS → REQUESTED` edges.) Each matching consult is reset to `REQUESTED` with `physician_id` cleared to null, `routing_basis` cleared to null, `updated_at` refreshed, and `version` incremented. The reset is keyed on the matched-license discriminator: a consult routed against a different physician or a different state, even if that physician happens to share another revoked license, is not affected.

Link three operates on the consults identified by link two: every `Prescription` under those consults whose current status is `DRAFT` is auto-voided. Each auto-voided prescription has its status set to `VOIDED`, its `void_reason` set to the literal `'LICENSE_REVOKED'`, its `updated_at` refreshed, its `version` incremented, and an `AuditEvent` of type `RX_VOIDED` appended per prescription with `actor_role` of `'system'`. Already-`ISSUED`, `TRANSMITTED`, or `DISPENSED` prescriptions are *not* touched by the cascade — the revoke does not retroactively unwind prescriptions that have already left the physician's hands; only drafts that were still on the bench are voided.

The whole cascade commits as a single atomic transaction: if any link fails, none of it takes effect, and a stale read after the cascade will see all three layers updated consistently. The serialization point this cascade creates is the answer to why `Consult.version` increments on link two: any other request holding an older `version` on that consult will fail OCC with `ERR_VERSION_CONFLICT`, ensuring revoke-vs-edit races resolve toward revocation.

### 3.7. Completing the Consult: Charge Calculation and the Billing/Follow-up Cascade

Once treatment is finished and every prescription under the consult is in a non-`DRAFT` state — meaning every `Prescription` is in `ISSUED`, `TRANSMITTED`, `DISPENSED`, or `VOIDED` — the assigned physician completes the consult. The completion drives a deterministic compute and cascade.

The base charge is read directly from the consult's `visit_tier`: a `BRIEF` consult is 5000 cents, a `STANDARD` consult is 10000 cents, and an `EXTENDED` consult is 18000 cents. That value is stored as `base_charge_cents` on the consult, and from there the `final_charge_cents` diverges by `billing_mode`.

In the **self-pay variant**, when `billing_mode` is `SELF_PAY`, the platform applies a courtesy discount of fifteen percent (1500 basis points): the discount in cents is the base charge multiplied by 0.15 and then rounded half-up to the nearest whole cent. The consult's `final_charge_cents` is the base charge minus that rounded discount. As a side effect of completion, a `SelfPayInvoice` row is created with `consult_id` equal to the completing consult, `subtotal_cents` equal to the base charge, `discount_cents` equal to the rounded discount, `amount_due_cents` equal to subtotal minus discount, and `status` set to `ISSUED`. There is exactly one `SelfPayInvoice` per self-pay consult; the uniqueness is enforced on `consult_id`. A `ComplianceOfficer` later marks the invoice paid, advancing it from `ISSUED` to `PAID`. A `SelfPayInvoice` may also reach `VOIDED` in lieu of payment.

In the **insurance variant**, when `billing_mode` is `INSURANCE`, the patient-owed amount is computed by a three-step waterfall over the base charge, **reading the patient's three insurance-economics fields at completion time and never afterward**. Step one applies the patient's remaining deductible: `deductible_applied_cents` is the smaller of the base charge and the patient's `insurance_deductible_remaining_cents`; let the leftover after this step be the base charge minus what was applied. Step two applies the flat copay: `copay_applied_cents` is the smaller of the step-one leftover and the patient's `insurance_copay_cents`; let the new leftover be the step-one leftover minus the copay. Step three applies coinsurance: `coinsurance_applied_cents` is the step-two leftover multiplied by the patient's `insurance_coinsurance_bps` divided by 10000, then rounded half-up to the nearest whole cent. The patient's `patient_responsibility_cents` is the sum of the three step amounts, and the consult's `final_charge_cents` equals that same sum. As a side effect, an `InsuranceClaim` row is created with `consult_id` equal to the completing consult, `billed_cents` equal to the base charge, the three waterfall components populated as above, `patient_responsibility_cents` set, `payer_paid_cents` initialized to 0, and `status` set to `SUBMITTED`. Like the self-pay case, exactly one `InsuranceClaim` per consult is permitted; a second creation attempt collides on the uniqueness constraint over `consult_id` and is rejected with `ERR_CLAIM_ALREADY_EXISTS`.

Independently of the billing branch, if the consult was created with `requires_followup` true, a `FollowUp` row is created with `consult_id` equal to the completing consult, `status` set to `SCHEDULED`, and `due_by` computed by the follow-up window rule. The window rule reads, across all prescriptions under this consult whose status is `ISSUED`, `TRANSMITTED`, or `DISPENSED` (drafts and voided prescriptions are excluded), the highest-precedence DEA schedule, where the precedence order from tightest to loosest is `II`, then `III`, then `IV`, then `V`, then `NONE`. When the maximum schedule is `II`, `due_by` is set to the current clock time plus 30 days. When the maximum schedule is `III`, `IV`, or `V` (and no `II` prescription is present), `due_by` is the current clock time plus 60 days. Otherwise — when no qualifying controlled-substance prescription exists, or all qualifying prescriptions have `dea_schedule` `NONE` — `due_by` is the current clock time plus 90 days. The computed `due_by` is recorded at second precision and is defensively required to be strictly later than the moment it is computed; a computed `due_by` that fails to advance past "now" is rejected with `ERR_FOLLOWUP_WINDOW_EMPTY`.

The `Payer` then progresses the `InsuranceClaim` through `SUBMITTED → APPROVED` or `SUBMITTED → DENIED` (the latter requiring a `denial_reason`); a `DENIED` claim can be appealed by a `ComplianceOfficer`, advancing it to `APPEALED`, from which the payer may again `APPROVED`. The payer marks an `APPROVED` claim as paid, which sets `payer_paid_cents` to `billed_cents` minus `patient_responsibility_cents`, decrements the patient's `insurance_deductible_remaining_cents` by `deductible_applied_cents` (floored at 0 so the field never goes negative), and appends an `AuditEvent` of type `CLAIM_PAID`. The conservation identity holds: the difference between the patient's pre-payment and post-payment `insurance_deductible_remaining_cents` equals `deductible_applied_cents`.

Concurrently with the billing flow, the assigned physician may complete a scheduled follow-up (advancing it from `SCHEDULED` to `COMPLETED` provided the current clock has not passed `due_by`); a compliance officer may cancel a scheduled follow-up (advancing to `CANCELLED`); and the nightly sweep — a `PlatformAdmin`-driven capability that does not itself require auth headers — promotes any `SCHEDULED` follow-up whose `due_by` is strictly earlier than the current clock to `MISSED`. The sweep appends an audit event per transitioned follow-up. The follow-up sweep is paired with an admin-only test-driving capability that advances the simulated clock to a supplied `to` instant; together these two utilities make the time-gated states (`EXPIRED` license, `MISSED` follow-up) reachable in tests.

Finally, a completed consult may be closed by a compliance officer. The close requires that billing has reached a terminal status — when `billing_mode` is `INSURANCE`, the `InsuranceClaim` must be in `PAID` or `DENIED`; when `billing_mode` is `SELF_PAY`, the `SelfPayInvoice` must be in `PAID` or `VOIDED` — and that the follow-up, if one was created, has reached one of `COMPLETED`, `MISSED`, or `CANCELLED`. If no follow-up was created (because `requires_followup` was false), that clause is vacuous. A close attempted against non-terminal billing or follow-up is rejected with `ERR_BILLING_NOT_TERMINAL`. The successful close advances the consult from `COMPLETED` to `CLOSED`, the second terminal state of the consult lifecycle (the first being `DECLINED`).

## 4. Endpoint Definitions

All endpoints are mounted under the `/telemed` URL prefix. Endpoints that create a new resource return HTTP 201 on success; all other successful mutations and reads return HTTP 200. Error responses follow §2.2.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/telemed/physicians` | Register a new physician. | `PlatformAdmin` |
| GET | `/telemed/physicians/{id}` | Read a physician. | `PlatformAdmin`, `ComplianceOfficer`, `Physician` |
| GET | `/telemed/physicians` | List physicians (paginated, filterable by `status`). | `PlatformAdmin`, `ComplianceOfficer` |
| POST | `/telemed/physicians/{id}/licenses` | Register a `StateLicense` under a physician. | `PlatformAdmin` |
| GET | `/telemed/physicians/{id}/licenses` | List a physician's licenses with projected `status` (filter by `state_code`, `status`). | `PlatformAdmin`, `ComplianceOfficer`, `Physician` |
| POST | `/telemed/physicians/{pid}/licenses/{lid}/revoke` | Revoke a license; cascades to consults and draft prescriptions. | `PlatformAdmin` |
| GET | `/telemed/physicians/{id}/compliance` | Read the physician's aggregate compliance score. | `PlatformAdmin`, `ComplianceOfficer` |
| POST | `/telemed/patients` | Register a patient. | `PlatformAdmin` |
| GET | `/telemed/patients/{id}` | Read a patient. | `PlatformAdmin`, `ComplianceOfficer`, `Physician` |
| PATCH | `/telemed/patients/{id}` | Update mutable patient fields. | `PlatformAdmin` |
| POST | `/telemed/consults` | Create a consult; snapshots `present_state_code`. | `ComplianceOfficer` |
| GET | `/telemed/consults/{id}` | Read a consult. | `ComplianceOfficer`, `Physician` |
| GET | `/telemed/consults` | List consults (filter by `status`, `billing_mode`, `present_state_code`). | `ComplianceOfficer`, `Physician` |
| POST | `/telemed/consults/{id}/route` | Compliance-route a `REQUESTED` consult to a physician. | `ComplianceOfficer` |
| POST | `/telemed/consults/{id}/decline` | Decline a `REQUESTED` consult (terminal `DECLINED`). | `ComplianceOfficer` |
| POST | `/telemed/consults/{id}/unroute` | Revert a `ROUTED` consult back to `REQUESTED` (only if no prescription exists). | `ComplianceOfficer` |
| POST | `/telemed/consults/{id}/start` | Physician starts a routed consult (`ROUTED → IN_PROGRESS`). | `Physician` |
| POST | `/telemed/consults/{id}/complete` | Physician completes; runs charge calculation and billing/follow-up cascades. | `Physician` |
| POST | `/telemed/consults/{id}/close` | Close a completed consult once billing and follow-up are terminal. | `ComplianceOfficer` |
| POST | `/telemed/consults/{cid}/prescriptions` | Create a `DRAFT` prescription under an `IN_PROGRESS` consult. | `Physician` |
| PATCH | `/telemed/prescriptions/{id}` | Edit a draft prescription (self-loop). | `Physician` |
| POST | `/telemed/prescriptions/{id}/issue` | Issue a draft (DEA + licensure + compliance-score checks). | `Physician` |
| POST | `/telemed/prescriptions/{id}/transmit` | Mark an issued prescription as transmitted to a pharmacy. | `Physician` |
| POST | `/telemed/prescriptions/{id}/mark-dispensed` | Mark a transmitted prescription as dispensed. | `ComplianceOfficer` |
| POST | `/telemed/prescriptions/{id}/void` | Void a non-dispensed prescription with `void_reason`. | `Physician` |
| GET | `/telemed/claims/{id}` | Read an insurance claim. | `ComplianceOfficer`, `Payer` |
| POST | `/telemed/claims/{id}/approve` | Payer approves a `SUBMITTED` or `APPEALED` claim. | `Payer` |
| POST | `/telemed/claims/{id}/deny` | Payer denies a `SUBMITTED` claim with `denial_reason`. | `Payer` |
| POST | `/telemed/claims/{id}/appeal` | Compliance appeals a `DENIED` claim. | `ComplianceOfficer` |
| POST | `/telemed/claims/{id}/mark-paid` | Payer marks an `APPROVED` claim paid; decrements deductible. | `Payer` |
| GET | `/telemed/invoices/{id}` | Read a self-pay invoice. | `ComplianceOfficer` |
| POST | `/telemed/invoices/{id}/mark-paid` | Mark a self-pay invoice paid. | `ComplianceOfficer` |
| GET | `/telemed/followups/{id}` | Read a follow-up. | `ComplianceOfficer`, `Physician` |
| POST | `/telemed/followups/{id}/complete` | Complete a scheduled follow-up (must be at or before `due_by`). | `Physician` |
| POST | `/telemed/followups/{id}/cancel` | Cancel a scheduled follow-up. | `ComplianceOfficer` |
| POST | `/telemed/_clock/advance` | Advance the simulated clock to `to`; unauthenticated. | `PlatformAdmin` |
| POST | `/telemed/_sweep/run` | Run the nightly follow-up sweep; unauthenticated. | `PlatformAdmin` |
| GET | `/telemed/audit-events` | List audit events (filter by `event_type`, `subject_entity`, `subject_id`). | `PlatformAdmin`, `ComplianceOfficer` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_NO_VALID_LICENSE` | 422 |
| `ERR_DEA_REQUIREMENTS_NOT_MET` | 422 |
| `ERR_SCHEDULE_II_REFILLS_FORBIDDEN` | 422 |
| `ERR_COMPLIANCE_SCORE_TOO_LOW` | 422 |
| `ERR_PHYSICIAN_MISMATCH` | 422 |
| `ERR_INSURANCE_NOT_ENROLLED` | 422 |
| `ERR_RX_FIELD_OUT_OF_RANGE` | 422 |
| `ERR_FOLLOWUP_WINDOW_EMPTY` | 422 |
| `ERR_BILLING_NOT_TERMINAL` | 409 |
| `ERR_CLAIM_ALREADY_EXISTS` | 409 |
| `ERR_PATIENT_HAS_ACTIVE_CONSULT` | 409 |
| `ERR_LICENSE_PERIOD_OVERLAP` | 409 |
| `ERR_PAGINATION_INVALID` | 400 |
