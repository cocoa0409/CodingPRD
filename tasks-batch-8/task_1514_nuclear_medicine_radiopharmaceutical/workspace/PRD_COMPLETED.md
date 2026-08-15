# Nuclear Medicine & Radiopharmaceutical Management API — Product Requirements Document

## 1. Introduction

A hospital nuclear medicine department operates under constraints that most clinical systems never face: its raw materials are radioactive isotopes that decay continuously and irreversibly, every becquerel of material on site is counted against a regulator-issued possession limit, and every handoff between staff members is audited under segregation-of-duties rules. Doses must be ordered against a half-life and a delivery window, patients must be scheduled to isotope arrival, every vial must be assayed in a dose calibrator before it touches a patient, waste must decay in storage for ten half-lives before it can leave the hot lab, and a single spill can contaminate a room, void its appointments, and quarantine every vial drawn for its patients. When a supplier shipment fails, the department needs a controlled substitution path rather than a cascade of silent cancellations.

This document specifies the Nuclear Medicine & Radiopharmaceutical Management API, the system of record for that department. It governs the isotope catalog, the radiopharmacy license register with its per-isotope conditions, the authorized-user list, patient registration, imaging room posture, isotope delivery scheduling and receipt, dose ordering and substitution, vial preparation and calibration, dose administration records, procedure appointments, waste containers and their clearance, radiation surveys, spill incident response, and patient release instructions. All server-side time is driven by a settable logical clock so that decay mathematics are deterministic, and all activity arithmetic follows a single, precisely specified rounding discipline.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All endpoints are mounted under the `/nuclear-medicine` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles: `DepartmentAdmin`, `AuthorizedUser`, `Radiopharmacist`, `NuclearMedicineTechnologist`, and `RadiationSafetyOfficer`. A request whose headers are missing or whose role is not one of these five is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `AuthorizedUser`, `X-User-ID` is the `id` of the acting `AuthorizedUser` record; ownership checks on any resource that references an `AuthorizedUser` compare the resource's foreign-key field — for a dose order, its `authorized_user_id` — to `X-User-ID`, and the identifier must reference an existing `AuthorizedUser` row or the call fails with `ERR_NOT_FOUND`. This entity-backed row check is enforced on the `AuthorizedUser` write endpoints (dose-order creation, cancellation, and substitution, and release-instruction issuance); read endpoints and other roles' endpoints do not resolve the row. When `X-User-Role` is `DepartmentAdmin`, `Radiopharmacist`, `NuclearMedicineTechnologist`, or `RadiationSafetyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `calibrated_by_user_id` on a vial, `sealed_by_user_id` on a waste container, `performed_by_user_id` on a survey, or `reported_by_user_id` on a spill incident) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0. A `limit` outside 1–100, a negative `offset`, or a non-integer value for either parameter is rejected with `ERR_VALIDATION` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order, with ties on the timestamp broken by `id`. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. The Logical Clock and Time Semantics

All server-side time in this system reads from a single logical clock, never from the wall clock; the one exception is the response envelope's `api_request_timestamp` (§2.2), which is generated from the wall clock and is not a business instant. Before any call has been made, the clock reads exactly `2026-08-01T00:00:00Z`. A `DepartmentAdmin`-only test-driving capability, `POST /nuclear-medicine/_clock/set_current_utc`, sets the clock to a supplied `to_iso8601` instant — any parsable ISO 8601 instant is accepted, earlier or later than the current value — and the response echoes the supplied string verbatim as `current_utc`. Every server-stamped instant in the system — `prepared_at`, `received_at`, `calibrated_at`, `administered_at`, `disposed_at`, `surveyed_at`, `sealed_at`, `certified_at`, `contained_at`, `decontaminated_at`, `cleared_at` — is taken from this clock.

Setting the clock is not a passive read change. Two sweep operations run on every clock set: first, every dose order still in `ORDERED` or `ON_HOLD` whose `expires_at` lies strictly earlier than the new clock value transitions to `EXPIRED`; second, every vial in `CALIBRATED` whose decay-corrected activity (exact variant of §2.5) has fallen strictly below its isotope's `min_usable_activity_mbq` transitions to `DECAYED`. After the sweep, the possession ledger described in §2.6 is recomputed.

Whenever decay mathematics compare two instants, the elapsed time is expressed in whole minutes, with any sub-minute remainder truncated toward zero, and both directions of the difference are defined — a target earlier than its reference yields a negative elapsed value that the tabular method handles by division (see §2.5).

### 2.5. Activity Arithmetic: Precision, Rounding, and the Two Decay-Correction Variants

All radioactivity values are expressed in megabecquerels (MBq) and are rounded half-up to three decimal places. When an isotope product is registered, the server also computes its `decay_constant_per_minute` as the natural logarithm of two divided by `half_life_minutes`, rounded half-up to six decimal places.

Decay correction takes a reference activity, a reference instant, a target instant, and a half-life, and produces the activity at the target instant. Two variants exist, and both are legitimate assay-correction methods:

- The **exact exponential variant** evaluates the decay in a single closed-form step: the reference activity is multiplied by one-half raised to the power of the elapsed whole minutes divided by the half-life in minutes, and the result is rounded half-up to three decimal places exactly once, at the end. This variant backs `assayed_activity_exact_mbq` on the administration record, the possession ledger, clearance evaluation, and the hot-lab capacity check.
- The **tabular minute-step variant** is the regulatory worksheet method. A per-minute decay factor is computed as one-half raised to the power of one divided by the half-life in minutes, rounded half-up to six decimal places. For a non-negative elapsed time, the running activity is multiplied by that factor and rounded half-up to three decimal places, once per elapsed minute, repeated for the full number of elapsed minutes. For a negative elapsed time, the running activity is divided by the factor and rounded half-up to three decimal places at each step, repeated for the absolute number of elapsed minutes. This variant backs `assayed_activity_tabular_mbq`.

The variants diverge because the tabular method rounds at every minute step while the exact method rounds only once. As a concrete illustration, 220.000 MBq of an isotope with a 110-minute half-life decayed over 110 minutes yields 110.000 MBq under the exact variant and 109.993 MBq under the tabular variant.

### 2.6. The Possession Ledger

Each radiopharmacy license carries a live possession total, `current_possession_mbq`, recomputed on every vial, delivery, or waste-container mutation and on every clock set. The total aggregates three components, each filtered to material whose isotope appears in that license's `isotope_conditions` (vials trace to a license through their order's prescribing authorized user):

1. **Vials** in `CALIBRATED` or `QUARANTINED` status — each contributes its `measured_activity_mbq` decay-corrected (exact variant) from its `calibrated_at` to the current instant.
2. **Deliveries** in `SCHEDULED` status — each contributes its `reference_activity_mbq` decay-corrected (exact variant) from its `reference_time_at` to the current instant.
3. **Waste containers** in `FILLING` or `SEALED` status — each contributes its own `current_activity_mbq`.

The rounding order is pinned: every component is individually rounded half-up to three decimal places before the sum is taken, and the sum itself is then rounded half-up to three decimal places. Summing raw values and rounding once at the end is a different, non-conformant order. Excluded from the ledger: vials in `PREPARED` (not yet assayed), vials in `DECAYED`, `ADMINISTERED`, or `DISPOSED`, deliveries in `RECEIVED` or `FAILED` (received material is tracked through its vials instead), and containers in `CLEARED`. Quarantining a vial does not remove it from the ledger.

### 2.7. Safety Postures and Segregation of Duties

Two posture gates protect the department. The license posture (`ACTIVE` or `SUSPENDED`) gates four operations: dose-order creation, delivery receipt, vial preparation, and dose administration. While a license is `SUSPENDED`, those four operations are rejected with `ERR_LICENSE_SUSPENDED` (HTTP 409). License expiry is exclusive: the current clock instant must be strictly earlier than the license's `expires_at`, and at or after that instant the same four operations are rejected with `ERR_LICENSE_EXPIRED` (HTTP 409). The room posture (`OPERATIONAL` or `CONTAMINATED`) is derived from open spill incidents and gates appointment booking: while a room is `CONTAMINATED`, booking an appointment in it is rejected with `ERR_ROOM_CONTAMINATED` (HTTP 409).

Segregation of duties pins three staff pairings. The technologist who administers a vial must not be the radiopharmacist who calibrated it: the administering `X-User-ID` must differ from the vial's `calibrated_by_user_id`. The officer who certifies a waste container's clearance must not be the officer who sealed it: the certifying `X-User-ID` must differ from the container's `sealed_by_user_id`. The officer who clears a spill incident must not be the person who reported it: the clearing `X-User-ID` must differ from the incident's `reported_by_user_id`. Violating any of the three pairings is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.8. Optimistic Concurrency Control

Exactly two write endpoints take a client-supplied version field, and on both it is non-optional. `POST /nuclear-medicine/dose-orders/{id}/substitute` requires `expected_order_version` carrying the version of the target dose order that the client last observed; if that value does not match the order's current `version` — because another write has advanced it since the client's last read — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client holding a stale view never creates a second superseding link on a chain it has not observed. `POST /nuclear-medicine/waste-containers/{id}/seal` requires `expected_container_version` carrying the client's last observed `version` of the target container; a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), because sealing freezes `intake_activity_mbq` and starts the ten-half-life decay clock, so a writer acting on a stale container view must restart from a fresh read. Endpoints not listed here do not accept a version field.

### 2.9. Validation Pipeline and Error Precedence

Every request is checked against an ordered validation pipeline, and only the first failure encountered is reported. When several rules guard the same call, evaluation proceeds in this global precedence order: authentication of the two headers comes first (`ERR_UNAUTHENTICATED`); then role authorization and ownership (`ERR_FORBIDDEN_ROLE`); then existence of every referenced identifier, path identifiers before body foreign keys (`ERR_NOT_FOUND`); then optimistic-concurrency version agreement on the two versioned endpoints (`ERR_STALE_VERSION`); then state-machine legality — the generic invalid-transition rejection (`ERR_INVALID_STATE`) and, for vial preparation specifically, the requirement that the referenced delivery already be received (`ERR_DELIVERY_NOT_RECEIVED`); then the safety family in rank order — license suspension (`ERR_LICENSE_SUSPENDED`), license expiry (`ERR_LICENSE_EXPIRED`), authorized-user standing (`ERR_USER_NOT_ACTIVE`), prescriber scope coverage (`ERR_USER_SCOPE_INSUFFICIENT`), isotope-condition coverage (`ERR_ISOTOPE_NOT_ON_LICENSE`), the prescribed-activity ceiling (`ERR_PRESCRIBED_ACTIVITY_EXCEEDS_LIMIT`), room contamination (`ERR_ROOM_CONTAMINATED`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), and possession limits (`ERR_POSSESSION_LIMIT_EXCEEDED`); then the temporal family — future scheduling (`ERR_SCHEDULE_IN_PAST`), administration-not-before-arrival (`ERR_ADMIN_BEFORE_DELIVERY`), the administration window (`ERR_OUTSIDE_ADMIN_WINDOW`), decayed-below-minimum activity (`ERR_DOSE_DECAYED_BELOW_MIN`), appointment overlap (`ERR_APPOINTMENT_OVERLAP`), hot-lab capacity (`ERR_HOT_LAB_CAPACITY_EXCEEDED`), waste clearance timing (`ERR_WASTE_CLEARANCE_TOO_EARLY`), and clearance activity (`ERR_CLEARANCE_ACTIVITY_EXCEEDED`); then the referential family — survey prerequisites (`ERR_SURVEY_REQUIRED`) and duplicate release instructions (`ERR_DUPLICATE_RELEASE_INSTRUCTION`); and finally the constraint family — delivery-activity sufficiency (`ERR_INSUFFICIENT_DELIVERY_ACTIVITY`), generic field validation (`ERR_VALIDATION`), duplicate license numbers (`ERR_DUPLICATE_LICENSE_NUMBER`), release criteria (`ERR_RELEASE_CRITERIA_NOT_MET`), and receipt tolerance (`ERR_ACTIVITY_TOLERANCE_EXCEEDED`).

Two qualifications pin this pipeline to the served behavior. First, ownership is evaluated against an existing target: the resource identified in the path is resolved (`ERR_NOT_FOUND`) before any ownership comparison is made, and on `POST /nuclear-medicine/patient-release-instructions` the administration named in the body is likewise resolved before the prescriber-ownership check. Second, field-level validation — a request body that is not a JSON object, a missing or null required field, a non-string value where a string is required, an unparsable timestamp, an invalid enum value, or an out-of-range pagination parameter — is raised at the point the request is parsed: after authentication, role authorization, and path-resource resolution, but before the state-machine and later guard families. Three endpoint-specific placements complete the picture: on order substitution the `use_type` enum check runs after the version and state checks (§3.3); on appointment booking the interval check (`end_at` strictly later than `start_at`) runs after the room-contamination gate and before overlap evaluation (§3.5); and on release-instruction issuance the `evaluation_variant` enum check runs before the referenced administration is resolved (§3.8).

Generic field validation (`ERR_VALIDATION`, HTTP 400) covers missing required fields, invalid enum values, a non-positive `half_life_minutes`, a booking whose `end_at` is not strictly later than its `start_at`, a non-positive patient `weight_kg`, a waste container whose isotope does not match the vial being disposed, and a missing or misplaced `measured_dose_rate_at_1m_usv_h` on release-instruction issuance.

### 2.10. Resource Identification and the Flat Topology

The resource topology is flat: every resource is a peer addressed at the top level, and resources reference one another through foreign keys carried in request bodies rather than through nested URL segments. Where a path does contain an identifier, identifiers are validated left to right, and identifiers inside the request body are validated after path identifiers; the first identifier that does not correspond to an existing resource yields `ERR_NOT_FOUND` (HTTP 404). A request to a path this document does not define, or to a defined path with an unsupported method, is likewise rejected with `ERR_NOT_FOUND` (HTTP 404).

Reverse reachability is provided by filtered list endpoints rather than nested routes. Authorized users can be filtered by `license_id`. Deliveries can be filtered by `isotope_product_id` and `status`. Dose orders can be filtered by `patient_id`, `isotope_product_id`, `authorized_user_id`, `replaces_order_id`, and `status`. Vials can be filtered by `order_id`, `delivery_id`, `waste_container_id`, and `status`. Administration records can be filtered by `order_id` and `vial_id`. Appointments can be filtered by `order_id`, `room_id`, and `status`. Waste containers can be filtered by `isotope_product_id`, `room_id`, and `status`. Surveys can be filtered by `room_id` and `result`. Spill incidents can be filtered by `room_id`, `isotope_product_id`, and `status`. Release instructions can be filtered by `administration_id`.

### 2.11. Common Resource Properties

Most resources share a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps taken from the logical clock and emitted in the clock's own precision: when the current clock value carries no fractional seconds they appear without a fractional part (for example, `2026-08-01T00:00:00Z`), and with three fractional digits otherwise. All other datetime fields carried on resources — the server-stamped instants of §2.4 as well as client-supplied instants such as `expires_at` and `occurred_at` — are always emitted in canonical UTC `Z` form with three fractional digits; client-supplied instants may carry any ISO 8601 offset (a missing offset is treated as UTC). `updated_at` refreshes on every mutation. The `version` field is an integer that starts at 1 on creation and increments by one on every mutation to the resource, including server-side cascade mutations such as a superseding substitution.

Two resources are append-only exceptions to this convention. A `DoseAdministration` record and a `RadiationSurvey` record each carry only `id` and `created_at`; both `updated_at` and `version` are absent on these two resources, because neither is ever modified after creation.

## 3. Business Logic & Workflows

### 3.1. Reference Data and the License Register

Before any clinical work can occur, a `DepartmentAdmin` builds the reference data. An isotope product is registered with a `name` (for example, "F-18 FDG"), a strictly positive `half_life_minutes` (a non-positive value is rejected with `ERR_VALIDATION`), and three regulatory thresholds: `spill_major_threshold_mbq` (the inclusive boundary at which an estimated spill activity classifies the spill as major), `release_activity_limit_mbq` (the inclusive administered-activity ceiling for activity-based patient release), and `min_usable_activity_mbq` (the assay floor below which a dose is clinically unusable). The server computes `decay_constant_per_minute` at registration as described in §2.5.

The radiopharmacy license is registered with a `license_number` that must be unique across all licenses — a duplicate is rejected with `ERR_DUPLICATE_LICENSE_NUMBER` (HTTP 409) — an aggregate `max_possession_mbq` ceiling, an exclusive `expires_at` instant, and an embedded `isotope_conditions` array. Each condition object names an `isotope_product_id`, a per-isotope `max_possession_mbq` ceiling, and an `allowed_use` of `DIAGNOSTIC`, `THERAPEUTIC`, or `BOTH`. A new license starts in `ACTIVE` status. Authorized users are then added to it with a `full_name`, the `license_id` of the license they practice under, a `scope` of `DIAGNOSTIC`, `THERAPEUTIC`, or `BOTH`, and an exclusive `expires_at`; a new user starts `ACTIVE`.

Suspension is the department's big stop button. When a `DepartmentAdmin` suspends a license — only an `ACTIVE` license may be suspended, otherwise the call is rejected with `ERR_INVALID_STATE` — the cascade runs in two hops. Hop one: every authorized user whose `license_id` points at this license and whose status is `ACTIVE` becomes `SUSPENDED`. Hop two: every dose order prescribed by one of those just-suspended users whose status is `ORDERED` or `DOSE_PREPARED` moves to `ON_HOLD`, with `hold_reason` set to `LICENSE_SUSPENDED` and `hold_previous_status` recording the status it occupied. Vials are deliberately not quarantined by this cascade — unlike the spill cascade of §3.6 — because a licensing problem does not make the physical dose unsafe. Reinstatement is the mirror image: only a `SUSPENDED` license may be reinstated (otherwise `ERR_INVALID_STATE`); suspended users return to `ACTIVE`, and every order sitting `ON_HOLD` with `hold_reason` of `LICENSE_SUSPENDED` returns to its recorded `hold_previous_status` with `hold_reason` cleared.

A user whose row is `SUSPENDED` or whose `expires_at` has been reached cannot act: order creation, order cancellation, order substitution, and release-instruction issuance by such a user are all rejected with `ERR_USER_NOT_ACTIVE` (HTTP 403).

### 3.2. Isotope Supply: Delivery Scheduling, Receipt, and Failure

A `Radiopharmacist` schedules an isotope delivery by supplying the `isotope_product_id`, the `scheduled_arrival_at` instant, the supplier-assayed `reference_activity_mbq`, and the `reference_time_at` instant that assay refers to. The delivery is created in `SCHEDULED` status.

Scheduling is guarded by the hot-lab aggregate capacity rule. Every delivery occupies a half-open arrival window that opens thirty minutes before its `scheduled_arrival_at` and closes thirty minutes after it — the window includes its opening instant and excludes its closing instant. The candidate set is every other delivery in `SCHEDULED` or `RECEIVED` status whose window intersects the new delivery's window with a non-empty intersection; windows that merely touch at an endpoint do not intersect, and `FAILED` deliveries never participate. Let the reference instant be the latest `scheduled_arrival_at` among the new delivery and all candidates. Each candidate's `reference_activity_mbq` is decay-corrected (exact variant) from its own `reference_time_at` to that reference instant, each such component is rounded half-up to three decimal places, the new delivery's own decayed contribution is rounded the same way, the components are summed, and the sum is rounded half-up to three decimal places. Only when this aggregate load is strictly greater than 37,000 MBq is the scheduling rejected with `ERR_HOT_LAB_CAPACITY_EXCEEDED` (HTTP 409); a load of exactly 37,000 MBq is accepted. Note the aggregate-capacity semantics: overlapping arrivals are allowed, and only the decayed sum at the reference instant is constrained — this differs from the imaging-room booking rule of §3.5, where any overlap is an exclusion.

When the shipment arrives, a `Radiopharmacist` receives it by recording `measured_activity_mbq`, the activity measured on receipt. The guards run in precedence order: the delivery must still be `SCHEDULED` (otherwise `ERR_INVALID_STATE`); the license must be `ACTIVE` (`ERR_LICENSE_SUSPENDED`) and unexpired (`ERR_LICENSE_EXPIRED`) — the license consulted here is the first-registered license whose `isotope_conditions` include the delivery's isotope, and if no registered license lists the isotope these two license checks are skipped; and the measured value must agree with the reference activity decayed from `reference_time_at` to the receipt instant — the absolute difference must be at most ten percent of that decayed reference value, a deviation of exactly ten percent passes, and anything larger is rejected with `ERR_ACTIVITY_TOLERANCE_EXCEEDED` (HTTP 422). On success, `received_at` is stamped from the logical clock and the delivery moves to `RECEIVED`.

When a shipment does not arrive or arrives unusable, the radiopharmacist marks the delivery failed, supplying a `reason` that the server stores in the delivery's `failure_reason` field; only a `SCHEDULED` delivery can be marked failed (otherwise `ERR_INVALID_STATE`). Marking a delivery failed is a supply-disruption hook, not an executioner: dependent dose orders are not auto-cancelled, and the prescriber resolves the disruption through the substitution path of §3.3.

### 3.3. The Dose Order: Prescription, Cancellation, and Substitution

An `AuthorizedUser` prescribes a dose order with a payload naming the `patient_id`, the `isotope_product_id`, a `use_type` of `DIAGNOSTIC` or `THERAPEUTIC`, the target `prescribed_activity_mbq` at the scheduled administration instant, and the `administration_scheduled_at` instant itself. The server stamps `authorized_user_id` with the caller's `X-User-ID`, creates the order in `ORDERED` status, and computes `expires_at` as the scheduled administration instant plus two half-lives of the prescribed isotope — after that point the dose order is stale and the clock sweep will expire it.

Creation runs a guard chain in precedence order. After authentication, role authorization, and resource existence — which always run first — the license posture is checked: suspended first (`ERR_LICENSE_SUSPENDED`), then expired (`ERR_LICENSE_EXPIRED`). Next, the prescriber's own standing: the authorized-user row must be `ACTIVE` and unexpired (`ERR_USER_NOT_ACTIVE`). Then the prescriber's `scope` must cover the order's `use_type` — a scope of `BOTH` covers everything — otherwise `ERR_USER_SCOPE_INSUFFICIENT` (HTTP 403). Then the isotope must appear in the license's `isotope_conditions` with an `allowed_use` that covers the `use_type`, otherwise `ERR_ISOTOPE_NOT_ON_LICENSE` (HTTP 409). Then the `prescribed_activity_mbq` must be at most the matching condition's `max_possession_mbq`, otherwise `ERR_PRESCRIBED_ACTIVITY_EXCEEDS_LIMIT` (HTTP 422). Then `administration_scheduled_at` must lie strictly in the future, otherwise `ERR_SCHEDULE_IN_PAST` (HTTP 422). Field validation of the payload is not deferred to the end: required-field presence is checked as the payload is parsed, before the resource-existence checks, and the `use_type` enum check runs after resource existence and before the license-posture check.

Cancellation belongs to the prescriber alone: the caller's `X-User-ID` must equal the order's `authorized_user_id`, otherwise the call is rejected with `ERR_FORBIDDEN_ROLE`. Cancellation is permitted from `ORDERED`, from `DOSE_PREPARED`, and from `ON_HOLD`; an order in any other state rejects the attempt with `ERR_INVALID_STATE`. An optional `reason` may accompany the request; it is accepted but not persisted on the order. A successful cancellation moves the order to the terminal `CANCELLED` status and decays out the order's open vials: every vial of the order in `PREPARED`, `CALIBRATED`, or `QUARANTINED` status becomes `DECAYED`.

Substitution is the supply-disruption mechanism, and it is the only way a superseding chain forms. The prescriber — again the caller must match the order's `authorized_user_id`, otherwise `ERR_FORBIDDEN_ROLE` — submits a payload carrying `expected_order_version` together with fresh clinical fields: `isotope_product_id`, `use_type`, `prescribed_activity_mbq`, and `administration_scheduled_at`. The version check runs before any state evaluation per §2.8: a stale `expected_order_version` is rejected with `ERR_STALE_VERSION`. Substitution is permitted from `ORDERED` and from `ON_HOLD`; from any other state the request is rejected with `ERR_INVALID_STATE`. The new payload re-validates as a fresh order — prescriber standing, scope coverage, isotope-condition coverage, the prescribed-activity ceiling, and future scheduling all apply to it. On success, a new dose order is created in `ORDERED` status for the same patient, with its `replaces_order_id` pointing at the original order; the original order moves to `SUPERSEDED`, its `superseded_by_order_id` is set to the new order's id, and its `version` increments by one. The original order's vials in `PREPARED` or `CALIBRATED` become `DECAYED`.

### 3.4. Vial Preparation and Calibration

With a received delivery in hand, a `Radiopharmacist` prepares a vial by submitting a payload containing the `order_id` and the `delivery_id`. The central question is how much activity must be drawn now so that, after decay, the prescribed activity is on hand at administration time.

The required activity is computed as follows. The elapsed time from the current clock instant to the order's `administration_scheduled_at` is expressed in whole minutes; order creation enforces future scheduling, but the clock can later advance past the scheduled instant while the order remains `ORDERED`, and in that case the negative difference is clamped to zero. An overage factor is then chosen from the isotope's half-life: 1.10 when the half-life is under 120 minutes, 1.05 when it is at least 120 minutes and at most 1440 minutes — a full day — and 1.00 when it exceeds 1440 minutes. The `prescribed_activity_mbq` is multiplied by two raised to the power of the elapsed minutes divided by the half-life in minutes, and that intermediate result is multiplied by the overage factor. The final product is rounded half-up to three decimal places in a single rounding applied at the end, and recorded as the vial's `required_activity_mbq`.

Preparation is guarded, in precedence order, by: the order must be in `ORDERED` status, otherwise `ERR_INVALID_STATE`; the referenced delivery must be `RECEIVED`, otherwise `ERR_DELIVERY_NOT_RECEIVED` (HTTP 409); the license must be `ACTIVE` (`ERR_LICENSE_SUSPENDED`) and unexpired (`ERR_LICENSE_EXPIRED`) — the license consulted is the license of the order's prescribing authorized user; the projected `current_possession_mbq` after the draw must not exceed either the license-wide `max_possession_mbq` or the matching isotope condition's `max_possession_mbq`, otherwise `ERR_POSSESSION_LIMIT_EXCEEDED` (HTTP 409); the order's `administration_scheduled_at` must not be earlier than the delivery's `scheduled_arrival_at`, otherwise `ERR_ADMIN_BEFORE_DELIVERY` (HTTP 409); and the delivery's reference activity decayed to the current instant must be at least the computed `required_activity_mbq`, otherwise `ERR_INSUFFICIENT_DELIVERY_ACTIVITY` (HTTP 409). Required-field validation of `order_id` and `delivery_id` runs as the payload is parsed, before the existence checks. On success the vial is created in `PREPARED` status with `prepared_at` stamped from the clock, `waste_container_id` left null, and the order advances from `ORDERED` to `DOSE_PREPARED`; the possession ledger is recomputed.

Calibration records the dose-calibrator assay. A `Radiopharmacist` submits `measured_activity_mbq` for the vial; the vial must be `PREPARED`, otherwise `ERR_INVALID_STATE`; and the assayed activity must be at least the isotope's `min_usable_activity_mbq`, otherwise the call is rejected with `ERR_DOSE_DECAYED_BELOW_MIN` (HTTP 409). On success, `calibrated_at` is stamped from the clock, `calibrated_by_user_id` records the calibrating radiopharmacist's `X-User-ID` — the segregation-of-duties anchor used at administration time — the vial moves to `CALIBRATED`, and the possession ledger is recomputed with the vial now counted at its measured activity.

Physical decay never stops. On every clock set, the sweep of §2.4 moves any `CALIBRATED` vial whose decay-corrected activity has fallen strictly below `min_usable_activity_mbq` into `DECAYED`, and cancel or supersede cascades move `PREPARED`, `CALIBRATED`, or `QUARANTINED` vials into `DECAYED` as described in §3.3.

### 3.5. Appointments and Dose Administration

A `NuclearMedicineTechnologist` (or a `DepartmentAdmin`) registers patients with a `full_name`, a strictly positive `weight_kg`, and an optional `date_of_birth` as an ISO calendar date, which is stored as supplied with no format validation applied. A `DepartmentAdmin` registers imaging and injection rooms with a `name` and an optional `cleanup_buffer_minutes`, which defaults to 15 minutes when omitted and must be an integer when supplied — a non-integer value is rejected with `ERR_VALIDATION`.

Booking an appointment binds an order to a room and a time interval. The technologist supplies `order_id`, `room_id`, `start_at`, and `end_at`. The referenced order must be in `ORDERED` or `DOSE_PREPARED` status, otherwise `ERR_INVALID_STATE`. The room must be `OPERATIONAL`; booking into a `CONTAMINATED` room is rejected with `ERR_ROOM_CONTAMINATED`. Intervals are half-open: a booking occupies its start instant and runs up to but not including its end instant, and the booking's `end_at` must be strictly later than its `start_at` (`ERR_VALIDATION`). For overlap checking, every existing `BOOKED` appointment in the same room is treated as occupying an interval extended by the room's `cleanup_buffer_minutes` — from its start up to but not including its end plus the buffer. A conflict exists whenever the new booking's start falls before an existing booking's buffer-extended end and that existing booking's start falls before the new booking's end; a new booking that starts exactly at another's buffer-extended end does not conflict, because half-open intervals that share only an endpoint have an empty intersection. A conflicting booking is rejected with `ERR_APPOINTMENT_OVERLAP` (HTTP 409). A new appointment starts in `BOOKED` status, and a technologist may cancel a `BOOKED` appointment, moving it to the terminal `CANCELLED` status — from any other status the cancellation is rejected with `ERR_INVALID_STATE` — optionally supplying a `reason`, which is accepted but not persisted.

Administration is the clinical climax. A `NuclearMedicineTechnologist` administers a vial, and the guards run in precedence order. The vial must be `CALIBRATED`, otherwise `ERR_INVALID_STATE`. The order's license must be `ACTIVE` (`ERR_LICENSE_SUSPENDED`) and unexpired (`ERR_LICENSE_EXPIRED`). The caller must differ from the vial's `calibrated_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`). The administration instant — the current clock value — must fall within sixty minutes of the order's `administration_scheduled_at` on either side: no earlier than sixty minutes before it and no later than sixty minutes after it, with both boundaries inclusive; the comparison is made on the whole-minute difference of §2.4 (sub-minute remainders truncated toward zero), so the check passes exactly when that truncated absolute difference is at most sixty minutes, and outside that window the call is rejected with `ERR_OUTSIDE_ADMIN_WINDOW` (HTTP 409). The exact-variant assay at the administration instant must be at least `min_usable_activity_mbq`; if it has decayed below that floor, the call is rejected with `ERR_DOSE_DECAYED_BELOW_MIN` and the vial automatically transitions to `DECAYED` — the failed administration is not merely refused, the dose is retired. The order itself must be in `DOSE_PREPARED` status, otherwise `ERR_INVALID_STATE`.

On success, an append-only administration record is created carrying the `order_id`, the `vial_id`, `administered_at` stamped from the clock, `administered_by_user_id` set to the caller's `X-User-ID`, both assay variants — `assayed_activity_exact_mbq` under the exact variant and `assayed_activity_tabular_mbq` under the tabular minute-step variant, each evaluated at the administration instant — and a `within_admin_window` boolean that is true exactly when the administration instant falls inside the sixty-minute window. The vial moves from `CALIBRATED` to `ADMINISTERED`, the order moves from `DOSE_PREPARED` to `ADMINISTERED`, and the completion bubbles up: the order's `BOOKED` appointment whose half-open interval contains the administration instant becomes `COMPLETED`.

### 3.6. Spill Response and Room Contamination

Any staff member — any of the five roles — may report a spill. The report carries the `room_id`, the spilled `isotope_product_id`, the `estimated_activity_mbq`, and the `occurred_at` instant, which may precede the report time. The server stamps `reported_by_user_id` with the reporter's `X-User-ID`, computes the incident's `classification`, and creates it in `REPORTED` status. The `classification` rule is an inclusive threshold comparison: an estimated activity at or above the isotope's `spill_major_threshold_mbq` classifies the incident `MAJOR`, and anything below it classifies the incident `MINOR`.

Creation itself fires the room cascade. The room transitions from `OPERATIONAL` to `CONTAMINATED`. Every `BOOKED` appointment in that room whose `end_at` is later than the spill's `occurred_at` transitions to `AUTO_VOIDED`, with `void_reason` set to the incident's id. Each voided appointment's order, if in `ORDERED` or `DOSE_PREPARED`, moves to `ON_HOLD` with `hold_reason` set to `SPILL_CONTAMINATION` and `hold_previous_status` recording its prior status. That order's vials in `PREPARED` or `CALIBRATED` move to `QUARANTINED` — quarantined vials remain counted in the possession ledger, because the material still exists.

A `RadiationSafetyOfficer` advances the incident by naming a `to_state`; a missing `to_state`, or a value other than `CONTAINED`, `DECONTAMINATED`, or `CLEARED`, is rejected with `ERR_VALIDATION`. From `REPORTED`, the incident moves to `CONTAINED`, stamping `contained_at` from the clock; from `CONTAINED`, it moves to `DECONTAMINATED`, stamping `decontaminated_at` from the clock while the room stays `CONTAMINATED`. The recontamination loop runs from `DECONTAMINATED` back to `CONTAINED` and is only legal when the latest radiation survey of the room recorded at or after `decontaminated_at` has result `FAIL` — otherwise the advance is rejected with `ERR_INVALID_STATE` — and the loop leg does not re-stamp `contained_at`, nor does the appointment/order/vial cascade fire again on this loop, because those resources are already voided, held, or quarantined. From `DECONTAMINATED`, the incident moves to `CLEARED` only when the latest survey of the room recorded at or after `decontaminated_at` has result `PASS` (otherwise `ERR_SURVEY_REQUIRED`, HTTP 409) and the clearing officer's `X-User-ID` differs from the incident's `reported_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`). Any advance that does not correspond to one of these transitions from the incident's current state is rejected with `ERR_INVALID_STATE`.

Clearance restores the department. Clearing stamps `cleared_at` and records `cleared_by_user_id`. If no other non-`CLEARED` spill incident references the same room, the room returns to `OPERATIONAL`; a second open incident holds the room contaminated on its own. Every order sitting `ON_HOLD` with `hold_reason` of `SPILL_CONTAMINATION` returns to its recorded `hold_previous_status` with `hold_reason` cleared, and each such order's `QUARANTINED` vials return to `CALIBRATED`. The appointments, however, stay `AUTO_VOIDED` — the compensation is deliberately asymmetric, and voided appointments are never resurrected.

Radiation surveys are the evidence layer for all of this. A `RadiationSafetyOfficer` records a survey with the `room_id`, the measured `ambient_dose_rate_usv_h`, and a `result` of `PASS` or `FAIL`; the server stamps `surveyed_at` from the clock and records `performed_by_user_id` from the caller's `X-User-ID`. Surveys are append-only: a failing survey recorded after decontamination is what legally authorizes the recontamination loop, and a passing one is what unlocks clearance.

### 3.7. Waste Decay-in-Storage and Clearance

Residual activity never leaves the hot lab immediately; it decays in storage. A `RadiationSafetyOfficer` creates a single-isotope waste container by naming its `isotope_product_id` and the storage `room_id`; the container starts in `FILLING` status.

Disposal routes vial residuals into a container. A `Radiopharmacist` disposes a vial that is `ADMINISTERED` or `DECAYED` — a vial in any other status rejects the disposal with `ERR_INVALID_STATE` — by naming the target `waste_container_id`. The container must be `FILLING` (otherwise `ERR_INVALID_STATE`), and its isotope must equal the isotope of the vial's order (otherwise `ERR_VALIDATION`). The residual computation depends on how the vial ended. For an administered vial, `residual_activity_mbq` is the un-administered remainder — the vial's `measured_activity_mbq` minus the administration's `assayed_activity_exact_mbq` — decayed from the administration instant to the disposal instant. For a decayed vial, where no administration occurred, `residual_activity_mbq` is the vial's `measured_activity_mbq` decayed from its `calibrated_at` to the disposal instant. In both cases `decay_loss_mbq` captures the activity lost to physical decay between calibration and disposal, and the vial-activity-balance invariant holds: the measured activity at calibration is fully accounted for as the sum of the administered activity, the residual routed to waste, and the decay loss. Disposal stamps `disposed_at`, moves the vial to `DISPOSED`, adds the residual rounded half-up to three decimal places into the container's `intake_activity_mbq`, and recomputes the possession ledger.

While a container is `FILLING`, its `current_activity_mbq` is computed by decaying each disposed vial's residual from its own `disposed_at` to the current instant, summing the results, and rounding half-up to three decimal places.

Sealing is the point of no return, and it is the second optimistic-concurrency checkpoint of §2.8: the sealing officer must supply `expected_container_version` matching the container's current `version`, with mismatches rejected as `ERR_STALE_VERSION`. The container must be `FILLING`, otherwise `ERR_INVALID_STATE`. Sealing stamps `sealed_at` from the clock, records `sealed_by_user_id` from the caller's `X-User-ID`, computes `clearable_after_at` as the sealing instant plus ten half-lives of the container's isotope, freezes `intake_activity_mbq` at its seal-time value, and increments the container's `version` by one. While `SEALED`, `current_activity_mbq` is computed as the frozen `intake_activity_mbq` multiplied by one-half raised to the power of the whole minutes elapsed since sealing divided by the half-life in minutes, rounded half-up to three decimal places.

Clearance certification is performed by a `RadiationSafetyOfficer` who must not be the officer who sealed the container — a certifying `X-User-ID` equal to `sealed_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. The container must be `SEALED`, otherwise `ERR_INVALID_STATE`. The current clock instant must be at or after `clearable_after_at`, otherwise `ERR_WASTE_CLEARANCE_TOO_EARLY` (HTTP 409) — the boundary is inclusive, so certifying exactly at the clearable instant is permitted. The container's `current_activity_mbq` must be at or below 0.05 MBq, otherwise `ERR_CLEARANCE_ACTIVITY_EXCEEDED` (HTTP 409). And the latest radiation survey of the storage room recorded at or after `sealed_at` must have result `PASS`, otherwise `ERR_SURVEY_REQUIRED`. On success, `certified_at` is stamped and `certified_by_user_id` recorded, the container moves to `CLEARED`, and it exits the possession ledger. Once `CLEARED`, the container's `current_activity_mbq` reads 0.000.

### 3.8. Patient Release Instructions

After administration, the prescribing authorized user decides whether the patient may be released under regulatory dose limits. Issuance is restricted: the caller must be the authorized user who prescribed the underlying order — releasing another prescriber's patient is rejected with `ERR_FORBIDDEN_ROLE` — and that prescriber must still be `ACTIVE` and unexpired (`ERR_USER_NOT_ACTIVE`).

The request names the `administration_id` and an `evaluation_variant` of `ACTIVITY_BASED` or `MEASURED_RATE_BASED`. The `measured_dose_rate_at_1m_usv_h` field must be present exactly when the measured-rate variant is chosen: omitting it under `MEASURED_RATE_BASED`, or supplying it under `ACTIVITY_BASED`, is rejected with `ERR_VALIDATION`. At most one instruction may exist per administration; a second issuance against the same administration is rejected with `ERR_DUPLICATE_RELEASE_INSTRUCTION` (HTTP 409).

Eligibility is variant-specific, and both boundaries are inclusive. Under `ACTIVITY_BASED`, the administration's `assayed_activity_exact_mbq` is compared against the isotope's `release_activity_limit_mbq`, and the patient is releasable when the assayed value is at or below that limit. Under `MEASURED_RATE_BASED`, the `measured_dose_rate_at_1m_usv_h` is compared against the regulatory dose-rate limit of 70 microsieverts per hour at one meter, and the patient is releasable when the measured rate is at or below 70; the assay figure is ignored entirely under this variant. The two variants can disagree for the same administration: an administration assayed at 1098.024 MBq of an iodine-131 product passes the activity-based evaluation against a 1221 MBq limit, while a measured rate of 80.0 microsieverts per hour fails the measured-rate evaluation against the 70 limit. When the chosen variant evaluates to not releasable, the request is rejected with `ERR_RELEASE_CRITERIA_NOT_MET` (HTTP 422) and no instruction row is persisted.

When the patient is releasable, the instruction is created with `releasable` set to true, status `ISSUED` — the only status an instruction ever carries, since instructions exist only for releasable patients — and `issued_by_user_id` recording the issuing authorized user's `X-User-ID`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; this includes order substitution (which creates the replacement order) and dose administration (which creates the administration record). Operations that modify an existing resource in place return `200 OK`, as does the clock-setting capability, and all list and detail reads return `200 OK`. Every `GET` endpoint is open to all five roles, denoted "Any" below; spill reporting is likewise open to any role. Request payloads, preconditions, and side effects are specified in §2 and §3; this table is only an index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/nuclear-medicine/_clock/set_current_utc` | Set the logical clock; runs the expiry/decay sweep and recomputes possession | DepartmentAdmin |
| POST | `/nuclear-medicine/isotope-products` | Register an isotope product | DepartmentAdmin |
| GET | `/nuclear-medicine/isotope-products` | List isotope products | Any |
| GET | `/nuclear-medicine/isotope-products/{id}` | Get one isotope product | Any |
| POST | `/nuclear-medicine/licenses` | Create a radiopharmacy license with embedded isotope conditions | DepartmentAdmin |
| GET | `/nuclear-medicine/licenses/{id}` | Get a license including its live `current_possession_mbq` | Any |
| POST | `/nuclear-medicine/licenses/{id}/suspend` | Suspend a license; cascades to its authorized users and their open orders | DepartmentAdmin |
| POST | `/nuclear-medicine/licenses/{id}/reinstate` | Reinstate a suspended license with the compensating cascade | DepartmentAdmin |
| POST | `/nuclear-medicine/authorized-users` | Add an authorized user to a license | DepartmentAdmin |
| GET | `/nuclear-medicine/authorized-users` | List authorized users (filterable by `license_id`) | Any |
| GET | `/nuclear-medicine/authorized-users/{id}` | Get one authorized user | Any |
| POST | `/nuclear-medicine/patients` | Register a patient | NuclearMedicineTechnologist, DepartmentAdmin |
| GET | `/nuclear-medicine/patients` | List patients | Any |
| POST | `/nuclear-medicine/imaging-rooms` | Register an imaging or injection room | DepartmentAdmin |
| GET | `/nuclear-medicine/imaging-rooms/{id}` | Get a room with its posture status | Any |
| POST | `/nuclear-medicine/isotope-deliveries` | Schedule an isotope delivery (hot-lab aggregate capacity enforced) | Radiopharmacist |
| GET | `/nuclear-medicine/isotope-deliveries` | List deliveries | Any |
| GET | `/nuclear-medicine/isotope-deliveries/{id}` | Get one delivery | Any |
| POST | `/nuclear-medicine/isotope-deliveries/{id}/receive` | Receive a delivery; measured activity tolerance is ten percent of the decayed reference | Radiopharmacist |
| POST | `/nuclear-medicine/isotope-deliveries/{id}/mark-failed` | Mark a scheduled delivery failed (supply-disruption contingency) | Radiopharmacist |
| POST | `/nuclear-medicine/dose-orders` | Prescribe a dose order | AuthorizedUser |
| GET | `/nuclear-medicine/dose-orders` | List dose orders | Any |
| GET | `/nuclear-medicine/dose-orders/{id}` | Get one dose order | Any |
| POST | `/nuclear-medicine/dose-orders/{id}/cancel` | Cancel an open order (prescriber only); open vials decay out | AuthorizedUser |
| POST | `/nuclear-medicine/dose-orders/{id}/substitute` | Supersede this order and create its replacement (optimistic concurrency on the order's version) | AuthorizedUser |
| POST | `/nuclear-medicine/dose-vials` | Prepare a vial for an order from a received delivery | Radiopharmacist |
| GET | `/nuclear-medicine/dose-vials` | List vials | Any |
| GET | `/nuclear-medicine/dose-vials/{id}` | Get one vial | Any |
| POST | `/nuclear-medicine/dose-vials/{id}/calibrate` | Record the dose-calibrator assay | Radiopharmacist |
| POST | `/nuclear-medicine/dose-vials/{id}/administer` | Administer the vial; creates the administration record with both assay variants | NuclearMedicineTechnologist |
| POST | `/nuclear-medicine/dose-vials/{id}/dispose` | Dispose an administered or decayed vial into a filling waste container | Radiopharmacist |
| GET | `/nuclear-medicine/dose-administrations` | List administration records | Any |
| GET | `/nuclear-medicine/dose-administrations/{id}` | Get one administration record | Any |
| POST | `/nuclear-medicine/procedure-appointments` | Book a procedure appointment for an order in a room | NuclearMedicineTechnologist |
| GET | `/nuclear-medicine/procedure-appointments` | List appointments | Any |
| GET | `/nuclear-medicine/procedure-appointments/{id}` | Get one appointment | Any |
| POST | `/nuclear-medicine/procedure-appointments/{id}/cancel` | Cancel a booked appointment | NuclearMedicineTechnologist |
| POST | `/nuclear-medicine/waste-containers` | Create a single-isotope decay-in-storage waste container | RadiationSafetyOfficer |
| GET | `/nuclear-medicine/waste-containers` | List waste containers | Any |
| GET | `/nuclear-medicine/waste-containers/{id}` | Get one waste container | Any |
| POST | `/nuclear-medicine/waste-containers/{id}/seal` | Seal the container; starts the ten-half-life decay clock (optimistic concurrency on the container's version) | RadiationSafetyOfficer |
| POST | `/nuclear-medicine/waste-containers/{id}/certify-clearance` | Certify a sealed container cleared for ordinary disposal | RadiationSafetyOfficer |
| POST | `/nuclear-medicine/radiation-surveys` | Record a room radiation survey | RadiationSafetyOfficer |
| GET | `/nuclear-medicine/radiation-surveys` | List surveys | Any |
| GET | `/nuclear-medicine/radiation-surveys/{id}` | Get one survey | Any |
| POST | `/nuclear-medicine/spill-incidents` | Report a spill; fires the room-contamination cascade | Any |
| GET | `/nuclear-medicine/spill-incidents` | List spill incidents | Any |
| GET | `/nuclear-medicine/spill-incidents/{id}` | Get one spill incident | Any |
| POST | `/nuclear-medicine/spill-incidents/{id}/advance` | Advance the spill workflow: contained, decontaminated, contained again on recontamination, or cleared | RadiationSafetyOfficer |
| POST | `/nuclear-medicine/patient-release-instructions` | Issue release instructions for an administration under a chosen evaluation variant | AuthorizedUser |
| GET | `/nuclear-medicine/patient-release-instructions` | List release instructions | Any |
| GET | `/nuclear-medicine/patient-release-instructions/{id}` | Get one release instruction | Any |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is only an index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DELIVERY_NOT_RECEIVED` | 409 Conflict |
| `ERR_LICENSE_SUSPENDED` | 409 Conflict |
| `ERR_LICENSE_EXPIRED` | 409 Conflict |
| `ERR_USER_NOT_ACTIVE` | 403 Forbidden |
| `ERR_USER_SCOPE_INSUFFICIENT` | 403 Forbidden |
| `ERR_ISOTOPE_NOT_ON_LICENSE` | 409 Conflict |
| `ERR_PRESCRIBED_ACTIVITY_EXCEEDS_LIMIT` | 422 Unprocessable Entity |
| `ERR_ROOM_CONTAMINATED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_POSSESSION_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_SCHEDULE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_ADMIN_BEFORE_DELIVERY` | 409 Conflict |
| `ERR_OUTSIDE_ADMIN_WINDOW` | 409 Conflict |
| `ERR_DOSE_DECAYED_BELOW_MIN` | 409 Conflict |
| `ERR_APPOINTMENT_OVERLAP` | 409 Conflict |
| `ERR_HOT_LAB_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_WASTE_CLEARANCE_TOO_EARLY` | 409 Conflict |
| `ERR_CLEARANCE_ACTIVITY_EXCEEDED` | 409 Conflict |
| `ERR_SURVEY_REQUIRED` | 409 Conflict |
| `ERR_DUPLICATE_RELEASE_INSTRUCTION` | 409 Conflict |
| `ERR_INSUFFICIENT_DELIVERY_ACTIVITY` | 409 Conflict |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_DUPLICATE_LICENSE_NUMBER` | 409 Conflict |
| `ERR_RELEASE_CRITERIA_NOT_MET` | 422 Unprocessable Entity |
| `ERR_ACTIVITY_TOLERANCE_EXCEEDED` | 422 Unprocessable Entity |
