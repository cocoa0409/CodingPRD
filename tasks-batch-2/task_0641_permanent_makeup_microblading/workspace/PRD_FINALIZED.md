# Permanent Makeup Studio API — Product Requirements Document

## 1. Introduction

Permanent makeup and microblading studios sit at the intersection of cosmetic artistry and regulated clinical practice. Every brow, eyeliner, or lip-blush procedure involves breaking the skin barrier, which means the studio must satisfy bloodborne-pathogen protocols, maintain valid practitioner licensing, verify client age and consent, and document an allergy patch-test before any pigment touches a client. This API exists to encode that operational and regulatory discipline directly into the booking and procedure workflow so that a procedure can never start unless every compliance gate has been cleared.

The platform models the full client journey: an intake consultation that yields a provisional healing-risk profile, an allergy patch-test with a mandatory cooling-off period, the booking and deposit of an initial procedure, the procedure itself (which consumes a single-use sterile kit), a healing follow-up phase, and the financial settlement of the session. Beyond the initial procedure the system tracks two longer-running cycles: a pre-paid touch-up package that lets a client return for retouches within a fixed window, and an annual color refresh. When healing goes poorly, a free corrective redo can be requested, approved, and scheduled as a new linked appointment, forming a revision loop back to a completed procedure.

The system is built for four cooperating roles — reception/scheduling staff, clinical technicians, a compliance authority, and a studio owner — and enforces a strict separation of duties between booking, clinical work, and regulatory approval. Because licensing lapses, kit shortages, and concurrent edits can all invalidate work that is already in flight, the API treats consistency as a first-class concern: license suspensions cascade into appointment voids, kit reversals, and deposit refunds, and contested writes are protected by optimistic concurrency control. All time-sensitive logic is driven by a server-controlled logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. A request missing either header, or carrying a header the server cannot interpret, is rejected with `ERR_UNAUTHENTICATED`. When the headers are present and valid but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled precisely as follows: `StudioAdmin`, `FrontDesk`, `Technician`, and `ComplianceOfficer`.

`StudioAdmin` is the owner/operator and a hierarchical superset: it manages the studio record, registers technicians, defines color formulas, sets the logical clock, and may read every resource in the system. When `X-User-Role` is `StudioAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

`FrontDesk` is reception, scheduling, and payments — it owns client registration, consent capture, bookings, deposits, balance collection, cancellations, no-shows, package purchases, and redo scheduling. When `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

`ComplianceOfficer` is the regulatory authority — it owns license suspension and reinstatement, patch-test voiding, appointment voiding, medical clearance, and redo approval/denial. As a segregation-of-duties measure, a `ComplianceOfficer` cannot book appointments or take payments. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

`Technician` is the clinical operator — it owns patch-test reads and the procedure progression of starting, finishing, and completing an appointment, along with authoring color formulas and healing logs. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician` entity; any ownership check on a resource that references a technician compares that resource's technician foreign key to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip from the start of the result set; when omitted it defaults to 0.

Unless a specific endpoint states otherwise, all list responses are sorted by `created_at` in ascending order.

Every list response includes these four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Each primary resource carries a server-minted `id` formatted as a UUID with no type prefix — the `id` conveys identity only and is never a meaningful payload value. Resources also carry a `created_at` timestamp, expressed in ISO 8601 UTC with three fractional digits, recording when the resource was first created.

Most resources additionally carry an `updated_at` timestamp (same ISO 8601 UTC, three-fractional-digit format), refreshed on every mutation, and a `version`, an integer that begins at 1 and increases by exactly 1 on every mutation — including mutations driven by cascades rather than direct client requests. The entities `Studio`, `Technician`, `Client`, `PatchTest`, `ColorFormula`, `Appointment`, `PackageOrder`, and `RedoRequest` all carry `updated_at` and `version`. Two entities are append-only audit records and carry only `id` and `created_at`: `ConsentRecord` and `DepositTransaction` have no `updated_at` and no `version`. `HealingLog` is likewise an append-only record carrying only `id` and `created_at` with no `updated_at` and no `version`.

All time-sensitive behavior is anchored to a server logical clock rather than the host wall clock. At startup the logical clock is fixed at exactly `2026-01-01T00:00:00Z`; before any clock-setting call it reads exactly this default and never falls back to wall-clock time. A `StudioAdmin` may advance the clock by supplying a target instant `to_iso8601`; every subsequent stamping of `applied_at`, `read_at`, `completed_at`, and every window or cooling-off comparison uses the logical clock's current value.

### 2.5. Precision, Rounding, and Money

All monetary amounts are stored and returned as integer cents. Wherever a calculation calls for rounding, the system uses the round-half-up method: a fractional cent of exactly one-half rounds up to the next whole cent. Rounding is applied at each rounding step as specified by the individual calculation, not deferred to the end of an unrelated computation. Risk scores and kit counts are plain integers and involve no rounding.

### 2.6. Hierarchical Consistency and Cascading Side Effects

A single operation frequently mutates more than one entity, and every such cascade must be applied in full. The most consequential cascade is a license suspension: when a `ComplianceOfficer` suspends a technician's license, every appointment of that technician currently in `BOOKED` lifecycle is voided (moved to `VOIDED`); for each voided appointment whose sterile kit had already been consumed, the kit is restored; for each voided appointment whose payment was in `DEPOSIT_PAID`, a deposit refund is issued and that appointment's payment moves to `REFUNDED`; the studio's compliance posture is then recomputed; and the studio's `version` is incremented. These secondary effects are not optional — they fire together as one logical settlement.

Whenever a derived field on a resource changes as a result of any operation (for example, a studio's kit ledger or compliance posture, a client's risk band or strike count, or an appointment's balance), that change is a mutation: it refreshes the resource's `updated_at` and increments its `version`. The server may also transition a resource on its own when criteria are met or violated — for example, marking a package exhausted or expired — without an explicit client request against that specific resource.

### 2.7. Nested Reference Validation

Resources in this system are flat peers linked by foreign keys rather than nested URL paths, but many write operations name several resources at once — a client, a technician, a color formula, and a patch test on a single booking. The server validates every referenced resource left-to-right in the order the operation reads them, and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource, before evaluating any business rule. Resource existence is therefore always checked before state, range, or safety constraints.

### 2.8. Optimistic Concurrency Control

Two write operations supersede a shared parent and therefore require an optimistic-concurrency token; no other endpoint takes a version field.

Scheduling a redo creates a new corrective appointment linked to the completed source appointment and is the operation that consumes the source's single redo allowance. A redo-scheduling request must carry `expected_appointment_version` matching the source appointment's current `version`. If the source appointment has been advanced since the client last observed it — for instance because another redo was already scheduled against it, which legitimately supersedes this one — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot act on a view of the source it no longer holds.

Booking a touch-up draws one session from a package order and decrements its remaining-session count. A touch-up booking must carry `expected_package_version` matching the package order's current `version`. If another touch-up booking has already drawn from the package since the client last read it — legitimately superseding the remaining-session count the client saw — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.9. Validation Ordering

When several validations could apply to one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then existence of every referenced resource (`ERR_NOT_FOUND`), then request well-formedness — required fields present, enums valid, numerics within their declared ranges, and foreign-key types consistent such as an appointment's procedure type matching its color formula's procedure type (`ERR_INVALID_REQUEST`). After those structural checks, the system verifies that the target resource is in a valid source state for the requested transition (`ERR_INVALID_STATE`). Only then are the domain-specific safety, temporal, fiscal, and referential checks evaluated; those checks and their individual error codes are described alongside the workflows they guard in Section 3. The optimistic-concurrency check on a superseding write is evaluated as the last gate before the write is applied.

Within the well-formedness layer, a numeric value submitted outside its declared range for the specific fields `reaction_grade`, `skin_sensitivity_self`, `pigment_count`, or `sterile_kit_total` is rejected with `ERR_VALIDATION_RANGE`. A `reaction_grade` or `skin_sensitivity_self` outside 0 to 3 inclusive, a `pigment_count` below 1, or a `sterile_kit_total` below 0 are the range violations this code covers.

### 2.10. Studio Compliance Posture and the Sterile-Kit Ledger

The studio maintains a single-use sterile-kit inventory for bloodborne-pathogen compliance. The studio is created with a `sterile_kit_total` count and tracks a derived `sterile_kit_consumed` count equal to the number of appointments scoped to this studio whose kit has been consumed and whose lifecycle is `IN_PROCEDURE`, `HEALING`, or `COMPLETED`. The derived `sterile_kit_available` is the total minus the consumed count, and is never negative — it is the larger of zero and that difference. The conservation invariant holds while consumed does not exceed total: consumed plus available always equals total.

The studio's `compliance_posture` is a derived enum with exactly three values. It is `OPEN` when at least one technician has license status `LICENSE_ACTIVE` and at least one sterile kit is available; it is `RESTRICTED` when no sterile kit is available (the available count is zero) but a licensed technician still exists; and it is `FROZEN` when no technician has license status `LICENSE_ACTIVE`. The posture is recomputed on any event that could change it — technician registration, license suspension, reinstatement or expiry, kit consumption, and kit restoration.

## 3. Business Logic & Workflows

### 3.1. Studio Setup, Technicians, and License Lifecycle

A `StudioAdmin` establishes the studio by supplying its trade `name`, its two-letter `state_code` (the US state of operation, such as CA, TX, or FL), an optional `min_client_age`, and the starting `sterile_kit_total`. The `state_code` drives the minimum legal procedure age; `min_client_age` defaults to 18 and may never be set below 18. At creation the studio's `sterile_kit_consumed` is zero and its compliance posture is computed — it begins `FROZEN` because no licensed technician yet exists. `min_client_age` must be at least 18 and `sterile_kit_total` must be at least 0; an out-of-range value is rejected as a malformed request.

A `StudioAdmin` or a `ComplianceOfficer` registers a `Technician` against a studio by supplying `studio_id`, the technician's `full_name`, their state `license_number`, the bloodborne-pathogen certification expiry `bbp_cert_expiry`, and the PMU `license_expiry` (both expiries are ISO 8601 UTC instants). A newly registered technician begins with `license_status` of `LICENSE_ACTIVE`; registration recomputes the studio's compliance posture and increments the studio's `version`.

A technician's license follows a three-state machine over `license_status`. A `ComplianceOfficer` may suspend an active license, moving it from `LICENSE_ACTIVE` to `LICENSE_SUSPENDED`; this is permitted only while the license is currently `LICENSE_ACTIVE`. Suspension triggers the full cascade described in Section 2.6: this technician's `BOOKED` appointments move to `VOIDED`, each voided appointment that had consumed a kit has that kit restored (its `kit_consumed` reset to false and the studio's `sterile_kit_consumed` reduced), each voided appointment in `DEPOSIT_PAID` receives a refund and moves to `REFUNDED`, the compliance posture is recomputed (becoming `FROZEN` if no `LICENSE_ACTIVE` technician remains), and the studio's `version` is incremented. The suspension request also carries `expected_studio_version` for the operator's reference to the studio it is mutating.

A `ComplianceOfficer` may reinstate a suspended license, moving it from `LICENSE_SUSPENDED` back to `LICENSE_ACTIVE`. Reinstatement is permitted only when the license is currently `LICENSE_SUSPENDED`, the `license_expiry` is strictly later than the current logical-clock time, and the `bbp_cert_expiry` is strictly later than the current logical-clock time. Reinstatement recomputes the compliance posture and increments the studio's `version`. Separately, the system treats a license as `LICENSE_EXPIRED` from either `LICENSE_ACTIVE` or `LICENSE_SUSPENDED` when, at any procedure-gating check, the `license_expiry` is at or before the current logical-clock time or the `bbp_cert_expiry` is at or before the current logical-clock time; this transition likewise recomputes the posture and increments the studio's `version`.

### 3.2. Client Intake and the Risk Profile

A `StudioAdmin` or `FrontDesk` operator registers a `Client` against a studio by supplying `studio_id`, the client's `full_name`, the `date_of_birth` (an ISO 8601 UTC date used for age verification), and three optional intake figures: `medical_flag_count` (the number of disclosed contraindicating medical conditions, default 0), `prior_adverse_reactions` (the count of prior PMU adverse reactions disclosed, default 0), and `skin_sensitivity_self` (a self-reported skin-sensitivity grade from 0 to 3, default 0). Each of `medical_flag_count` and `prior_adverse_reactions` must be at least 0, and `skin_sensitivity_self` must fall within 0 to 3 inclusive. On registration the client's `no_show_strikes` is 0, the `client_status` is `ACTIVE`, and `medical_cleared` is false.

Each client carries an observed sensitivity grade, `skin_sensitivity_observed`, which remains null until a patch test for that client is read, at which point it takes the read's reaction grade (0 to 3). The client's `risk_score` is computed by a weighted sum: the medical-flag count is weighted by 8, the prior-adverse-reaction count is weighted by 12, and a sensitivity figure is weighted by 5; the three weighted terms are summed into an integer with no rounding. The sensitivity figure used is the observed grade `skin_sensitivity_observed` whenever a patch test for the client has been read (that is, whenever the observed grade is not null), and otherwise the self-reported `skin_sensitivity_self`. At intake, before any patch test has been read, the provisional variant uses the self-reported grade; once a patch test is read, the final variant uses the observed grade, which overrides the self-report.

The client's `risk_band` is a derived enum: it is `HIGH_RISK` when the `risk_score` is at least 30, and `STANDARD` when the `risk_score` is below 30. A `HIGH_RISK` client may not be booked unless `medical_cleared` is true; that flag is set true only by a `ComplianceOfficer` granting medical clearance, an action that increments the client's `version`.

A client also accumulates no-show strikes. The derived `no_show_strikes` is the count of this client's appointments in lifecycle `NO_SHOW`, and the derived `client_status` is `BLOCKED` when the strike count is at least 3 and `ACTIVE` when it is below 3. A `BLOCKED` client cannot be booked.

### 3.3. Consent, Patch-Test, and the Cooling-Off Period

Before any booking, the studio must hold the client's signed paperwork. A `FrontDesk` or `ComplianceOfficer` operator records a `ConsentRecord` by supplying `client_id`, a `consent_type` of `PROCEDURE_CONSENT`, `MEDICAL_DISCLOSURE`, or `PHOTO_RELEASE`, the boolean `age_verified` (true when front-desk staff confirmed a government ID and that the client meets the studio's minimum age at signing), and the `signed_by_name` as signed by the client. Consent records are immutable audit entries; they carry only `id` and `created_at`.

A patch test screens for pigment allergy. A `Technician` or `FrontDesk` operator applies a patch test by supplying the `client_id`; the test begins with a `status` of `APPLIED` and `applied_at` stamped at the current logical-clock time. The test's `read_at` and `reaction_grade` remain null until the result is read, and `result` is null until then as well. A patch test's `status` follows a state machine with `APPLIED` as the initial state and `READ` and `VOIDED` as terminal states. The package order and redo request likewise each track their own `status` enumeration, described in Sections 3.7 and 3.8.

A `Technician` reads the result, moving the test from `APPLIED` to `READ`. The read is permitted only when the test is currently `APPLIED`, the current logical-clock time is at or after the applied time plus the mandatory 48-hour patch-read minimum, and a `reaction_grade` from 0 to 3 inclusive is supplied. These checks follow the Section 2.9 ordering: the supplied `reaction_grade` is range-validated first (an out-of-range grade is `ERR_VALIDATION_RANGE`), then the `APPLIED` state is verified (`ERR_INVALID_STATE`), and only then — because the 48-hour patch-read minimum is a temporal domain check evaluated after the state check — is the elapsed-time precondition enforced; reading before the applied time plus the 48-hour minimum, while the test is validly `APPLIED`, is rejected with `ERR_COOLING_OFF_VIOLATION` rather than `ERR_INVALID_STATE`. On a successful read the system stamps `read_at` at the current logical-clock time, computes `result` as `PASS` when the reaction grade is at most 1 and `FAIL` when the reaction grade is at least 2, copies the reaction grade onto the client's `skin_sensitivity_observed`, recomputes the client's `risk_score` and `risk_band` using the final post-patch-test variant, and increments the client's `version`. A `ComplianceOfficer` may instead void an applied test, moving it from `APPLIED` to `VOIDED`; this is permitted only while the test is `APPLIED`, after which the test can no longer gate an appointment.

### 3.4. Color Formulas and Session Pricing

A `StudioAdmin` or `Technician` defines a `ColorFormula` by supplying `studio_id`, a display `name` (for example, "Warm Taupe"), the `procedure_type` it is intended for (`BROWS`, `EYELINER`, or `LIP_BLUSH`), and the `pigment_count` — the number of pigments blended, which must be at least 1 and which drives a color surcharge tier.

The price of a procedure session, `session_price_cents`, is computed at booking from three components evaluated in a pinned order: first the base rate, then the color surcharge, then the corrective uplift, and finally their sum. The base rate is determined by the appointment's `procedure_type`: a brows procedure has a base of 60000 cents, an eyeliner procedure 50000 cents, and a lip-blush procedure 70000 cents. The color surcharge is determined by the linked formula's `pigment_count`: it is 0 when the pigment count is 1 or fewer, 5000 cents when the count is exactly 2, and 12000 cents when the count is 3 or more. The corrective uplift applies only when `is_corrective` is true: it is the base rate multiplied by 0.25 and rounded half-up to whole cents; when `is_corrective` is false the uplift is 0. The session price is then the base plus the color surcharge plus the corrective uplift. These standard mechanics apply when the appointment kind is `INITIAL` or `TOUCH_UP`.

Two appointment kinds override this. For an `ANNUAL_REFRESH` appointment the session price is simply the base rate multiplied by 0.50 and rounded half-up to whole cents, with the color surcharge and corrective uplift both dropped. For a `REDO` appointment the session price is 0.

The deposit required, `deposit_required_cents`, is computed immediately after the session price as 20 percent of the session price, rounded half-up to whole cents. A `REDO` appointment, whose session price is 0, has a required deposit of 0.

### 3.5. Booking an Initial Procedure and Its Safety Gates

A `FrontDesk` operator books an initial procedure by supplying the `client_id`, the `technician_id`, the `color_formula_id`, the `patch_test_id` (the read, passing patch test that gates this procedure), the `procedure_type`, an optional `is_corrective` flag (default false), and the `scheduled_start` (an ISO 8601 UTC instant). A new booking begins with `lifecycle_status` of `BOOKED`, `payment_status` of `AWAITING_DEPOSIT`, and `appointment_kind` of `INITIAL`; its `session_price_cents` and `deposit_required_cents` are computed as in Section 3.4 and its `balance_due_cents` initializes to the full session price.

Booking enforces a layered set of safety, temporal, fiscal, and referential gates, evaluated after the structural checks of Section 2.9. The well-formedness check requires, among other things, that the appointment's `procedure_type` equal the linked color formula's procedure type; a mismatch is an `ERR_INVALID_REQUEST`. The remaining gates apply in priority order as follows.

First, age must be verified: at booking, the whole number of years between the client's `date_of_birth` and the `scheduled_start` must be at least the studio's `min_client_age`, and a consent record with `age_verified` set true must exist on file for the client; failure raises `ERR_AGE_NOT_VERIFIED`. Next, consent must be present: a `ConsentRecord` of type `PROCEDURE_CONSENT` for the client must exist before booking (and a `PHOTO_RELEASE` consent is required before any photo-flagged operation); absence raises `ERR_CONSENT_MISSING`. Next, the patch-test gate: the linked patch test must be in status `READ` with `result` of `PASS` — a `FAIL` result or any non-read test blocks the booking with `ERR_PATCH_TEST_FAILED`. Next, the cooling-off rule: the `scheduled_start` must be at or after the patch test's `applied_at` plus the 48-hour patch-read minimum, otherwise `ERR_COOLING_OFF_VIOLATION`. Next, the high-risk gate: if the client's `risk_band` is `HIGH_RISK`, the client's `medical_cleared` must be true, otherwise `ERR_MEDICAL_CLEARANCE_REQUIRED`. Finally, the blocked-client gate: the client's `client_status` must be `ACTIVE` rather than `BLOCKED` by three or more no-show strikes, otherwise `ERR_CLIENT_BLOCKED`.

### 3.6. Deposits, Procedure Progression, and the Kit Ledger

Once an appointment exists, payment evolves on its own axis, `payment_status`, independent of the lifecycle. A `BOOKED` appointment can move from `AWAITING_DEPOSIT` to `DEPOSIT_PAID` without any lifecycle change. A `FrontDesk` operator collects the deposit by supplying the `amount_cents` to charge; this is permitted only while the payment status is `AWAITING_DEPOSIT`, and the charged `amount_cents` must equal the appointment's `deposit_required_cents` or the charge is rejected with `ERR_DEPOSIT_AMOUNT_MISMATCH`. A successful collection emits a `CHARGE` deposit transaction and recomputes `deposit_paid_cents` to equal the required deposit.

Every money event is recorded as an append-only `DepositTransaction` carrying `id`, `created_at`, the `appointment_id`, a `txn_type` of `CHARGE` (deposit collected), `REFUND` (deposit returned), or `FORFEIT` (deposit kept on a late cancel or no-show), and a positive `amount_cents`; for a `CHARGE` the amount must equal the appointment's required deposit. The appointment's derived `deposit_paid_cents` is the sum of `CHARGE` amounts minus the sum of `REFUND` amounts across that appointment's transactions; a `FORFEIT` does not reduce `deposit_paid_cents`, because forfeited money is kept by the studio rather than returned. The derived `balance_due_cents` equals `session_price_cents` minus `deposit_paid_cents` while the payment status is `AWAITING_DEPOSIT`, `DEPOSIT_PAID`, or `BALANCE_DUE`, and is 0 once the payment status is `PAID_IN_FULL`.

A `Technician` starts the procedure, advancing the lifecycle from `BOOKED` to `IN_PROCEDURE`. Starting is permitted only when the lifecycle is `BOOKED`, the payment status is `DEPOSIT_PAID` or `PAID_IN_FULL`, the technician's `license_status` is `LICENSE_ACTIVE`, the studio's `compliance_posture` is `OPEN`, at least one sterile kit is available, and the linked patch test is `READ` with `result` `PASS`. These start preconditions are evaluated in their listed order: the combined license-and-posture gate first, then the kit-availability gate, then the patch-test gate. A license or posture failure at start raises `ERR_LICENSE_INVALID`; an absence of an available kit raises `ERR_NO_STERILE_KIT`; a non-passing patch test raises `ERR_PATCH_TEST_FAILED`. Because the posture-`OPEN` requirement already incorporates the kit ledger (per Section 2.10 a studio with a licensed technician but no available kit is `RESTRICTED`, not `OPEN`), a start attempted while no sterile kit is available — and a licensed technician still exists — fails the license-and-posture gate first and is therefore rejected with `ERR_LICENSE_INVALID`; the dedicated kit-availability gate (and its `ERR_NO_STERILE_KIT`) is reached only after the posture gate has passed. On a successful start the appointment's `kit_consumed` is set true, the studio's `sterile_kit_consumed` increases by 1 and `sterile_kit_available` is recomputed, the compliance posture is recomputed (becoming `RESTRICTED` if the available count reaches 0), and the studio's `version` is incremented.

A `Technician` finishes the needling work, which is a single call that advances the lifecycle from `IN_PROCEDURE` to `HEALING` and, on the parallel payment axis, advances the payment status from `DEPOSIT_PAID` to `BALANCE_DUE`; the payment advance is permitted only when the payment status is `DEPOSIT_PAID` and the lifecycle is `IN_PROCEDURE`, and it sets `balance_due_cents` to the session price minus the deposit already paid. A `FrontDesk` operator then collects the remaining balance by supplying the `amount_cents`, moving the payment status from `BALANCE_DUE` to `PAID_IN_FULL`; this is permitted only while the payment status is `BALANCE_DUE`, the supplied `amount_cents` must equal the appointment's `balance_due_cents` (otherwise `ERR_DEPOSIT_AMOUNT_MISMATCH`), and on success `balance_due_cents` becomes 0.

### 3.7. Healing, Completion, and the Revision Cycle

After the needling work, the appointment sits in `HEALING` awaiting aftercare follow-ups. A `Technician` or `FrontDesk` operator records a `HealingLog` against a `HEALING` or `COMPLETED` appointment by supplying the `appointment_id`, the `day_offset` (whole days since the procedure, at least 0), an `outcome_flag` of `GOOD` (healing on track) or `POOR` (retention loss or complication), and optional `notes`. If the logged appointment is already `COMPLETED` and the outcome flag is `POOR`, the appointment's `healing_outcome` is recomputed to `POOR` and the appointment's `version` is incremented. Healing logs are append-only audit entries carrying only `id` and `created_at`.

A `Technician` completes the appointment, advancing the lifecycle from `HEALING` to `COMPLETED`. Completion is permitted only when the lifecycle is `HEALING`, the payment status is `PAID_IN_FULL`, and at least one healing log exists for the appointment. On completion the system stamps `completed_at` at the current logical-clock time and sets `healing_outcome` to `POOR` if any healing log for the appointment carries a `POOR` outcome flag and to `GOOD` otherwise. The completion time anchors two windows: the touch-up window running from 30 days after completion to 60 days after completion, and annual-refresh eligibility beginning 365 days after completion. If the completed appointment is a `REDO` linked to a redo request in status `SCHEDULED`, that redo request is moved to `FULFILLED`.

When a healing outcome is poor, the client is entitled to one free corrective redo. A `FrontDesk` or `ComplianceOfficer` operator opens a `RedoRequest` against the completed appointment by supplying the `appointment_id` and a `reason`; the request begins in status `REQUESTED`. A redo is eligible only when the source appointment is `COMPLETED` with `healing_outcome` of `POOR` and the current logical-clock time is at or before the source's `completed_at` plus the 90-day redo window; an ineligible request is rejected with `ERR_REDO_NOT_ELIGIBLE`, and this same eligibility is re-checked at approval time. A redo request follows a state machine with `REQUESTED` as its initial state and `DENIED` and `FULFILLED` as terminal states.

A `ComplianceOfficer` approves a redo, moving it from `REQUESTED` to `APPROVED`; approval requires that the request be `REQUESTED`, the linked appointment be `COMPLETED` with `healing_outcome` `POOR`, and the current time be within the 90-day redo window. Alternatively a `ComplianceOfficer` denies the request, moving it from `REQUESTED` to `DENIED` with no redo appointment created. A `FrontDesk` operator schedules an approved redo, moving it from `APPROVED` to `SCHEDULED`; scheduling requires the request be `APPROVED` and the supplied source-appointment version token described in Section 2.8. Scheduling creates a new appointment of kind `REDO` whose `parent_appointment_id` is the source appointment, with `session_price_cents` of 0, `deposit_required_cents` of 0, `payment_status` of `PAID_IN_FULL`, and `lifecycle_status` of `BOOKED`; the redo request's `redo_appointment_id` is set to the new appointment and the source appointment's `version` is incremented. When that redo appointment is later completed, its redo request bubbles up to `FULFILLED`, closing the loop from a `COMPLETED` source through `REQUESTED → APPROVED → SCHEDULED` to `FULFILLED`. To schedule the redo appointment the operator also supplies the `scheduled_start`, `technician_id`, `color_formula_id`, and `patch_test_id` for the new corrective procedure.

### 3.8. Touch-Up Packages and Annual Refresh

After an initial procedure completes, a client may buy a pre-paid touch-up bundle. A `FrontDesk` operator purchases a `PackageOrder` by supplying the `client_id`, the `source_appointment_id` (the completed initial appointment whose touch-ups this package extends), the `included_sessions` (at least 1), and the `pricing_mode`. The package begins in status `ACTIVE`, its `remaining_sessions` initialized to the included count, and its `package_price_cents` computed from the pricing mode. The derived `remaining_sessions` thereafter equals the included sessions minus the count of touch-up appointments referencing this package that are not in `CANCELLED` or `VOIDED`. A package order follows a state machine with `ACTIVE` as its initial state and `EXHAUSTED` and `EXPIRED` as terminal states.

The package price hinges on two opposite rounding strategies. The per-touch-up gross is the source appointment's session price multiplied by 0.40 (each touch-up is priced at 40 percent of a full session). Under the pay-as-you-go mode (`PAYG`, the provisional treatment), each touch-up line is rounded half-up individually and then those rounded lines are summed: the per-line amount is the per-touch-up gross rounded half-up, and the package price is that rounded line multiplied by the number of included sessions. Under the bundle mode (`BUNDLE`, the final discounted treatment), the products are summed first and then rounded once: the gross is the per-touch-up gross multiplied by the number of included sessions, and the package price is that gross multiplied by (1 minus the 15 percent bundle discount), rounded half-up exactly once. For the same source price and session count the two modes deliberately yield different cent totals because they pin opposite rounding orders.

A package transitions on its own under two conditions. When a touch-up booking draws the last remaining session so that `remaining_sessions` reaches 0, the package moves from `ACTIVE` to `EXHAUSTED` and no further touch-up appointments may reference it. When the source appointment's touch-up window has closed — the current logical-clock time is later than the source's `completed_at` plus 60 days — and remaining sessions still exist, the package moves from `ACTIVE` to `EXPIRED`, its remaining sessions void, and no further touch-ups may be booked from it.

A `FrontDesk` operator books a touch-up by supplying the `package_order_id`, the `technician_id`, the `color_formula_id`, the `patch_test_id`, the `procedure_type`, the `scheduled_start`, and the `expected_package_version` concurrency token. The new appointment begins `BOOKED` and `AWAITING_DEPOSIT` with kind `TOUCH_UP`, its `parent_appointment_id` set to the package's source appointment and its `package_order_id` set; its session price is computed by the standard session mechanics and its deposit follows. Booking draws one session from the package: the package's `remaining_sessions` is decremented, its `version` is incremented, and it becomes `EXHAUSTED` if remaining reaches 0. A touch-up booking is gated by the touch-up window — the `scheduled_start` must fall within the source's `completed_at` plus 30 days through the source's `completed_at` plus 60 days, and the package must be `ACTIVE` with `remaining_sessions` greater than 0, otherwise `ERR_TOUCHUP_WINDOW_CLOSED`. Touch-up bookings are also subject to the same age, consent, cooling-off, high-risk, and blocked-client gates as initial bookings.

A `FrontDesk` operator books an annual refresh by supplying the `parent_appointment_id` (the completed appointment being refreshed), the `technician_id`, the `color_formula_id`, the `patch_test_id`, the `procedure_type`, and the `scheduled_start`. The new appointment begins `BOOKED` and `AWAITING_DEPOSIT` with kind `ANNUAL_REFRESH`, and its session price uses the annual-refresh variant (50 percent of base only). An annual-refresh booking is gated by the annual-refresh window: the `scheduled_start` must be at or after the source appointment's `completed_at` plus 365 days, otherwise `ERR_REFRESH_NOT_DUE`. Annual-refresh bookings are also subject to the age, consent, high-risk, and blocked-client gates.

### 3.9. Cancellations, No-Shows, and Compliance Voids

A `FrontDesk` operator cancels a `BOOKED` appointment, moving the lifecycle from `BOOKED` to `CANCELLED`; cancellation is permitted only while the lifecycle is `BOOKED`. The financial outcome turns on timing: if the current logical-clock time is at or before the `scheduled_start` minus the 48-hour free-cancel window, the studio issues a full refund — a `REFUND` deposit transaction for the full `deposit_paid_cents` and the payment status moves to `REFUNDED`. Otherwise the cancellation is late: the studio emits a `FORFEIT` deposit transaction for the `deposit_paid_cents`, the deposit is kept, and the payment status remains `DEPOSIT_PAID`. Deposit conservation holds across both branches: the deposit paid equals the amount refunded plus the amount forfeited.

A `FrontDesk` operator marks a `BOOKED` appointment a no-show, moving the lifecycle from `BOOKED` to `NO_SHOW`; this is permitted only while the lifecycle is `BOOKED` and the current logical-clock time is at or after the `scheduled_start`. A no-show emits a `FORFEIT` deposit transaction for the `deposit_paid_cents` (the deposit is forfeited), recomputes the client's `no_show_strikes` upward by one, recomputes the client's `client_status` (becoming `BLOCKED` if the strike count reaches at least 3), and increments the client's `version`.

A `ComplianceOfficer` may void a `BOOKED` appointment directly, moving the lifecycle from `BOOKED` to `VOIDED`; voiding is permitted only while the lifecycle is `BOOKED`. The same void is also produced by the cascade when a technician's license is suspended or expires. On a void, if the appointment had consumed a kit, the kit is restored — `kit_consumed` is reset to false and the studio's `sterile_kit_consumed` is reduced by 1, preserving kit conservation — and the studio's `version` is incremented; and if the payment status was `DEPOSIT_PAID`, a `REFUND` deposit transaction is emitted for the `deposit_paid_cents` and the payment status moves to `REFUNDED`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state-transition actions and money collections — return a `200 OK` status code. The logical-clock setter also returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StudioAdmin |
| POST | `/studios` | Create the studio | StudioAdmin |
| GET | `/studios/{id}` | Read studio incl. kit ledger and posture | StudioAdmin, FrontDesk, Technician, ComplianceOfficer |
| POST | `/technicians` | Register a technician | StudioAdmin, ComplianceOfficer |
| GET | `/technicians/{id}` | Read technician | StudioAdmin, FrontDesk, Technician, ComplianceOfficer |
| GET | `/technicians` | List technicians; filter by studio_id | StudioAdmin, FrontDesk, Technician, ComplianceOfficer |
| POST | `/technicians/{id}/suspend-license` | Suspend a technician's license | ComplianceOfficer |
| POST | `/technicians/{id}/reinstate-license` | Reinstate a suspended license | ComplianceOfficer |
| POST | `/clients` | Register a client | StudioAdmin, FrontDesk |
| GET | `/clients/{id}` | Read client incl. risk band, strikes, status | StudioAdmin, FrontDesk, Technician, ComplianceOfficer |
| GET | `/clients` | List clients; filter by studio_id | StudioAdmin, FrontDesk, ComplianceOfficer |
| POST | `/clients/{id}/medical-clearance` | Grant medical clearance for a HIGH_RISK client | ComplianceOfficer |
| POST | `/consent-records` | Record a signed consent / medical disclosure / photo release | FrontDesk, ComplianceOfficer |
| GET | `/consent-records/{id}` | Read a consent record | StudioAdmin, FrontDesk, ComplianceOfficer |
| GET | `/consent-records` | List consent records; filter by client_id | StudioAdmin, FrontDesk, ComplianceOfficer |
| POST | `/patch-tests` | Apply a patch test on a client | Technician, FrontDesk |
| GET | `/patch-tests/{id}` | Read a patch test | StudioAdmin, FrontDesk, Technician, ComplianceOfficer |
| GET | `/patch-tests` | List patch tests; filter by client_id | StudioAdmin, FrontDesk, Technician, ComplianceOfficer |
| POST | `/patch-tests/{id}/read` | Read patch-test result (≥48h after applied_at) | Technician |
| POST | `/patch-tests/{id}/void` | Void an applied patch test | ComplianceOfficer |
| POST | `/color-formulas` | Create a pigment color formula | StudioAdmin, Technician |
| GET | `/color-formulas/{id}` | Read a color formula | StudioAdmin, FrontDesk, Technician, ComplianceOfficer |
| GET | `/color-formulas` | List color formulas; filter by studio_id | StudioAdmin, FrontDesk, Technician, ComplianceOfficer |
| POST | `/appointments` | Book an INITIAL procedure appointment | FrontDesk |
| GET | `/appointments/{id}` | Read an appointment incl. both state dimensions and money fields | StudioAdmin, FrontDesk, Technician, ComplianceOfficer |
| GET | `/appointments` | List appointments; filter by client_id, technician_id, color_formula_id, patch_test_id, parent_appointment_id, package_order_id | StudioAdmin, FrontDesk, Technician, ComplianceOfficer |
| POST | `/appointments/{id}/deposit` | Collect the deposit (CHARGE) | FrontDesk |
| POST | `/appointments/{id}/start` | Start the procedure (consume sterile kit) | Technician |
| POST | `/appointments/{id}/finish-procedure` | Finish the needling work; move to HEALING and BALANCE_DUE | Technician |
| POST | `/appointments/{id}/pay-balance` | Pay the remaining balance | FrontDesk |
| POST | `/appointments/{id}/complete` | Complete the appointment after healing follow-up | Technician |
| POST | `/appointments/{id}/cancel` | Cancel a BOOKED appointment (refund or forfeit by 48h rule) | FrontDesk |
| POST | `/appointments/{id}/no-show` | Mark a BOOKED appointment a no-show after scheduled_start | FrontDesk |
| POST | `/appointments/{id}/void` | Void a BOOKED appointment (restores kit, refunds deposit) | ComplianceOfficer |
| POST | `/appointments/touch-up` | Book a TOUCH_UP appointment drawing one session from a package | FrontDesk |
| POST | `/appointments/annual-refresh` | Book an ANNUAL_REFRESH appointment off a COMPLETED appointment | FrontDesk |
| POST | `/packages` | Purchase a touch-up package off a COMPLETED INITIAL appointment | FrontDesk |
| GET | `/packages/{id}` | Read a package order | StudioAdmin, FrontDesk, ComplianceOfficer |
| GET | `/packages` | List packages; filter by client_id, source_appointment_id | StudioAdmin, FrontDesk, ComplianceOfficer |
| GET | `/deposit-transactions/{id}` | Read a deposit transaction | StudioAdmin, FrontDesk, ComplianceOfficer |
| GET | `/deposit-transactions` | List deposit transactions; filter by appointment_id | StudioAdmin, FrontDesk, ComplianceOfficer |
| POST | `/healing-logs` | Record a healing/aftercare follow-up | Technician, FrontDesk |
| GET | `/healing-logs/{id}` | Read a healing log | StudioAdmin, FrontDesk, Technician, ComplianceOfficer |
| GET | `/healing-logs` | List healing logs; filter by appointment_id | StudioAdmin, FrontDesk, Technician, ComplianceOfficer |
| POST | `/redo-requests` | Open a redo request against a COMPLETED appointment with POOR healing | FrontDesk, ComplianceOfficer |
| GET | `/redo-requests/{id}` | Read a redo request | StudioAdmin, FrontDesk, Technician, ComplianceOfficer |
| GET | `/redo-requests` | List redo requests; filter by appointment_id or redo_appointment_id | StudioAdmin, FrontDesk, Technician, ComplianceOfficer |
| POST | `/redo-requests/{id}/approve` | Approve a redo request (eligibility re-checked) | ComplianceOfficer |
| POST | `/redo-requests/{id}/deny` | Deny a redo request | ComplianceOfficer |
| POST | `/redo-requests/{id}/schedule` | Schedule the free REDO appointment (OCC on the source appointment) | FrontDesk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_AGE_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_CONSENT_MISSING` | 422 Unprocessable Entity |
| `ERR_PATCH_TEST_FAILED` | 422 Unprocessable Entity |
| `ERR_COOLING_OFF_VIOLATION` | 422 Unprocessable Entity |
| `ERR_MEDICAL_CLEARANCE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CLIENT_BLOCKED` | 422 Unprocessable Entity |
| `ERR_LICENSE_INVALID` | 422 Unprocessable Entity |
| `ERR_NO_STERILE_KIT` | 422 Unprocessable Entity |
| `ERR_TOUCHUP_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_REFRESH_NOT_DUE` | 422 Unprocessable Entity |
| `ERR_REDO_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_VALIDATION_RANGE` | 422 Unprocessable Entity |
