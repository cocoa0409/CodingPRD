# Oncology Infusion API — Product Requirements Document

## 1. Introduction

The Oncology Infusion API is the system of record for an outpatient chemotherapy and infusion center. It coordinates the work of three professional groups — the oncology pharmacist who owns protocols and drug orders, the infusion nurse who mixes, double-checks, and administers therapy at the chairside, and the prior-authorization coordinator who secures payer approval for specialty drugs. The domain is unusually unforgiving: a cytotoxic dose miscalculated by a factor or administered without an independent second check is a patient-safety event, not a billing inconvenience. Every rule encoded here exists because a real infusion center carries that risk on every cycle.

The platform models the full arc of cancer treatment. A pharmacist authors a reusable **regimen protocol** (a named order set such as FOLFOX) and publishes it as an immutable template. Patients are anchored to a protocol through a **treatment cycle**, whose body-surface-area and renal-clearance measurements are frozen at activation so that every dose in the cycle is computed against one consistent snapshot. Individual **drug orders** are dosed by body surface area, by the Calvert AUC renal formula, or as a flat dose; the system computes how many single-use vials must be drawn, how much drug is discarded, and whether that waste is billable under the Medicare JW modifier. Each chemotherapy order travels through a mandatory two-nurse verification gate before it can be administered. In parallel, chairs and nurses are scheduled as overlapping time intervals subject to double-booking and nursing-acuity limits, prior authorizations are consumed mg-by-mg as drug is administered, and toxicity reactions of sufficient severity automatically suspend the entire cycle and tear down its open work.

This document specifies the API contract a backend engineer must implement. Section 2 fixes the system-wide envelope, authentication, pagination, concurrency, and the cross-cutting safety and arithmetic principles. Section 3 narrates the business workflows in the order a clinical team lives them. Sections 4 and 5 enumerate the endpoints and the error catalogue. The structural contract in Section 2 is exact; the business behavior in Section 3 must be assembled by reading the workflow narratives in full.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, principles, and boilerplate that apply across the entire API. The whole API is mounted under the `/infusion-center` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_AUTH`. The system recognizes exactly three roles, spelled precisely as `Pharmacist`, `Nurse`, and `PriorAuthCoordinator`. When a well-authenticated caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The three roles relate to persisted identity differently. When `X-User-Role` is `Nurse`, `X-User-ID` is the `id` of the acting `Nurse` entity; any operation whose behavior depends on *which* nurse acted — preparing, verifying, rejecting, or administering a drug order — reads the acting nurse's identity directly from `X-User-ID`, and the server records it on the order (for example as `prepared_by_nurse_id` or `verified_by_nurse_id`). When `X-User-Role` is `Pharmacist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server authorizes the action by role but does not compare the value to any entity's `id`. When `X-User-Role` is `PriorAuthCoordinator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any stored record.

Authorization is enforced per operation. All three roles may issue any read (`GET`) request. The pharmacist owns patient, protocol, order-set, chair, nurse, treatment-cycle, and drug-order creation, plus the cycle lifecycle transitions of activation, resume, advancing, and abandonment. The nurse owns the chairside order actions and appointment check-in and completion. The prior-authorization coordinator owns opening and deciding prior authorizations. A handful of operations are shared: placing a cycle on hold, cancelling a drug order, booking and cancelling an appointment, and recording a toxicity event may all be performed by either a `Nurse` or a `Pharmacist`. The precise authorized role for each endpoint is listed in Section 4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set; when omitted it defaults to 0.

Unless an endpoint states otherwise, list results are sorted by the `created_at` timestamp in ascending order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in this system carry a common set of server-managed fields. The `id` is a server-minted UUID assigned at creation; it carries no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed when the resource is first written. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at its creation value and increments by one on each mutation; it is the basis for the optimistic-concurrency mechanism described in Section 2.6.

Every entity in this system — `Patient`, `RegimenProtocol`, `OrderSetItem`, `Chair`, `Nurse`, `PriorAuthorization`, `TreatmentCycle`, `DrugOrder`, `InfusionAppointment`, and `ToxicityEvent` — carries the full quartet of `id`, `created_at`, `updated_at`, and `version`. There are no append-only resources here that omit `updated_at` or `version`.

### 2.5. Hierarchical Consistency and Cascades

The treatment cycle is the consistency root for the clinical work beneath it. When a cycle leaves its operational state — whether suspended onto hold or abandoned outright — the system does not leave its in-flight drug orders and appointments dangling. Instead it tears them down as part of the same operation, cancelling them and freeing the chair and nurse intervals they reserved, then bumps the cycle's own `version` and refreshes its `updated_at`. The exact membership of each cascade, and the order in which the two cascade steps run, is specified in the workflow narratives of Section 3; the principle to hold here is that a single cycle transition can mutate many child rows atomically, and each such transition is one version increment on the cycle.

Because these cascades silently advance the cycle's `version`, a client that read the cycle before a cascade and then tries to book new work against the stale version it observed must be turned away rather than allowed to attach work to a schedule that was just dismantled. Section 2.6 makes that rule precise.

When a child mutation has no bearing on its parent's state, the parent is left untouched; cascades flow only downward from a cycle transition, never upward from an individual order or appointment action.

### 2.6. Optimistic Concurrency Control on Cycle Booking

Booking an infusion appointment is the one write in this system guarded by optimistic concurrency. The create-appointment operation requires a non-optional `expected_treatment_cycle_version` field in its request body, carrying the `version` of the target `TreatmentCycle` that the client last observed. The server compares that value to the cycle's current `version`. If they do not match — meaning another writer, very often a hold or abandon cascade, has advanced the cycle since the client read it — the booking is rejected with `ERR_STALE_CYCLE_VERSION` and HTTP status 412, and no appointment is created. This prevents a booking that was composed against a now-defunct schedule from slipping a fresh appointment onto a cycle whose appointments were just cancelled. No other endpoint in this system accepts or requires a version field; only appointment creation participates in this check.

### 2.7. Dose Arithmetic, Snapshots, and the JW Waste Principle

Dosing in oncology is computed against frozen measurements, not live ones. At the moment a cycle is activated, the patient's current body-surface-area value and current glomerular filtration rate are copied onto the cycle as immutable snapshots; every dose computed for that cycle reads those snapshots, so that later edits to the patient's height, weight, or renal function never retroactively change an active cycle's doses. Body surface area itself is the Mosteller value: the square root of the patient's height in centimeters multiplied by the weight in kilograms, that product divided by 3600, with the result rounded half-up to two decimal places.

Dose figures are computed to whole milligrams. The ordered dose is rounded half-up to zero decimal places after the dose reduction is applied to the unrounded base — never round the base before reducing. Vial counts are whole numbers obtained by rounding up to the next whole vial. The detailed formula, the Calvert renal cap, and the vial/waste derivation live in Section 3 where they belong to the drug-order workflow; the principle to carry forward is that dose milligrams are integers, the half-up rounding rule applies, and waste is the difference between what a whole number of single-use vials supplies and what the patient actually receives. Whenever that waste is positive, the discarded drug is billable under the JW modifier.

### 2.8. Temporal Scheduling Semantics

Chair and nurse scheduling is interval-based and uses half-open intervals. An appointment occupies the span from its `start_at` up to but not including its `end_at`. Two intervals overlap only when each starts strictly before the other ends; intervals that merely touch — one ending exactly when the next begins — do not overlap and may share a chair or nurse back-to-back. This adjacency rule governs both the chair double-booking check and the nurse acuity check. Only appointments in the `SCHEDULED` or `CHECKED_IN` states occupy a chair or contribute to a nurse's load; cancelled or completed appointments free their interval.

### 2.9. Segregation of Duties

Chemotherapy verification is a controls boundary, not a formality. The system enforces that the nurse who prepares a drug order cannot be the nurse who independently verifies it, and cannot be the nurse who rejects it back for re-preparation. This separation, together with the requirement that the verifier hold a chemotherapy certification and that the verifier re-enter the computed dose for an independent match, forms the double-verification gate detailed in Section 3. The specific rejection codes for each leg of this gate are introduced alongside the workflow they guard.

### 2.10. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: a missing or malformed header yields `ERR_MISSING_AUTH` (401) before anything else is considered. Role authorization is next; a forbidden role yields `ERR_FORBIDDEN_ROLE` (403). Resource existence is third — every id referenced in the path and then in the body is resolved left-to-right, path identifiers before body identifiers, and the first that fails to resolve yields its resource-specific not-found error (404): `ERR_PATIENT_NOT_FOUND` for a patient, `ERR_PROTOCOL_NOT_FOUND` for a regimen protocol, `ERR_ORDER_SET_ITEM_NOT_FOUND` for an order set item, `ERR_CHAIR_NOT_FOUND` for a chair, `ERR_NURSE_NOT_FOUND` for a nurse, `ERR_PRIOR_AUTH_NOT_FOUND` for a prior authorization, `ERR_CYCLE_NOT_FOUND` for a treatment cycle, `ERR_DRUG_ORDER_NOT_FOUND` for a drug order, `ERR_APPOINTMENT_NOT_FOUND` for an infusion appointment, and `ERR_TOXICITY_EVENT_NOT_FOUND` for a toxicity event. Request-body well-formedness is fourth: required fields present, enums within their allowed sets, numerics within their declared ranges, an appointment's `end_at` strictly after its `start_at`, and the dose field matching the order item's dosing method must all hold, or the request is rejected with `ERR_INVALID_REQUEST` (400). The optimistic-concurrency check on appointment booking is fifth, yielding `ERR_STALE_CYCLE_VERSION` (412) when the supplied cycle version is stale. State-legality is sixth: the target resource must be in a state from which the requested transition is legal — and for drug-order creation and appointment check-in, the parent cycle must be `ACTIVE` — otherwise a state-specific 409 such as `ERR_CYCLE_NOT_ACTIVE` is returned. Only after all of the foregoing pass are the domain-specific safety, scheduling, referential, and fiscal rules of the operation evaluated; their relative ordering within a single endpoint is described in the workflow that introduces them.

### 2.11. Status Codes

Creating a new, distinct resource returns HTTP 201. Every state transition, lifecycle action, update, and other modification of an existing resource returns HTTP 200. List and fetch reads return HTTP 200.

## 3. Business Logic & Workflows

### 3.1. Patients and Body-Surface-Area

A `Pharmacist` registers a patient by supplying a unique medical record number `mrn`, the patient's `full_name`, a `height_cm` and `weight_kg` both required to be strictly greater than zero, and a `gfr_ml_min` glomerular filtration rate, also strictly greater than zero, which feeds the Calvert renal dosing formula. On registration the patient's `status` is `ACTIVE`, and the system immediately computes the Mosteller body-surface-area value `bsa_m2`: take the height in centimeters times the weight in kilograms, divide that product by 3600, take the square root, and round half-up to two decimal places. For a 170 cm, 70 kg patient this is the square root of 170 times 70 divided by 3600, which is the square root of roughly 3.3056, giving 1.82 after rounding.

The anthropometric and renal figures are mutable. A pharmacist may update any of `height_cm`, `weight_kg`, or `gfr_ml_min`; whenever height or weight changes, `bsa_m2` is recomputed by the same Mosteller rule, and the patient's `version` increments. A patient may also be marked deceased, which sets `status` to `DECEASED` and increments `version`; this action carries no state precondition, so it succeeds regardless of the patient's current `status` (marking an already-`DECEASED` patient simply re-sets `DECEASED` and bumps `version`). The patient `status` enumeration is therefore exactly `ACTIVE` or `DECEASED`. Patients can be listed, optionally narrowed by `mrn`, and fetched individually.

### 3.2. Building and Publishing a Regimen Protocol

Treatment templates are authored as regimen protocols. A `Pharmacist` creates a protocol in `DRAFT` status with a unique `code` (for example FOLFOX), a display `name`, a `cycle_length_days` of at least 1, and a `total_cycles` count of at least 1. A protocol's `status` enumeration is `DRAFT` or `PUBLISHED`.

While a protocol is still `DRAFT`, the pharmacist attaches **order set items** to it. Each item names its parent protocol by carrying the `regimen_protocol_id`, the `drug_name`, and a `role` that is either `CHEMO` or `PREMED` — premedications are sequenced before chemotherapy items. The item's `dosing_method` is one of `BSA`, `AUC`, or `FLAT`, and the dosing field that must accompany it depends on that choice: a `BSA` item requires `dose_per_m2` (milligrams per square meter), an `AUC` item requires `target_auc`, and a `FLAT` item requires `flat_dose_mg`. Whichever of these the dosing method requires must be present and strictly greater than zero. Supplying the body of an item whose dosing method's required dose field is absent is a malformed request. Every item also declares a `vial_size_mg`, the milligram capacity of one single-use vial and strictly greater than zero, which drives waste computation; a `day_offset` of at least 1 fixing which day within a cycle the item runs, where day 1 is the first day of the cycle; and a required integer `sequence_index` (no minimum) that orders items within a day, lower running earlier. Order set items can be listed, optionally filtered by `regimen_protocol_id`, and fetched by id.

Publishing transitions a protocol from `DRAFT` to `PUBLISHED` and is performed by a pharmacist. Two preconditions guard it: the protocol must have at least one order set item, or the publish is rejected with `ERR_NO_ORDER_SET_ITEMS`; and it must have at least one order set item whose `role` is `CHEMO`, or the publish is rejected with `ERR_NO_CHEMO_ITEM`. Once published, the protocol and all of its order set items become immutable templates — no further items attach to a published protocol, which is why item attachment is confined to the `DRAFT` window; an attempt to attach an item to a protocol whose `status` is not `DRAFT` is rejected as a malformed request with `ERR_INVALID_REQUEST`. `PUBLISHED` is the protocol's terminal state.

### 3.3. Chairs and Nurses

Infusion chairs are the physical capacity of the center. A `Pharmacist` creates a chair with a unique `label` and an optional `is_isolation` flag, defaulting to false, that marks negative-pressure isolation bays. A chair opens in `OPEN` status; its `status` enumeration is `OPEN` or `CLOSED`. A pharmacist may close a chair, setting `status` to `CLOSED` and incrementing its `version`; closing carries no state precondition and succeeds regardless of the chair's current `status` (re-closing an already-`CLOSED` chair re-sets `CLOSED` and bumps `version`), and a closed chair refuses new bookings. Chairs can be listed and fetched.

Nurses are the staffing capacity. A pharmacist creates a nurse with a `full_name`, an `is_chemo_certified` flag defaulting to false that marks the nurses permitted to verify and administer chemotherapy, and a `max_acuity_load` defaulting to 6 and required to be at least 1 — the ceiling on the summed nursing acuity of a nurse's concurrently overlapping appointments. Nurses can be listed and fetched. The acting `Nurse` for a chairside action is identified by `X-User-ID` as described in Section 2.1.

### 3.4. Prior Authorization for Specialty Drugs

Specialty chemotherapy drugs require payer approval before they can be billed and administered. A `PriorAuthCoordinator` opens a prior authorization by supplying the `patient_id` it covers, the `drug_name`, and the `payer`. A new authorization begins in `REQUESTED` status with `consumed_units_mg` initialized to 0 and `authorized_units_mg` initialized to null until an approve decision records it. The `status` enumeration runs `REQUESTED`, `APPROVED`, `DENIED`, and `EXHAUSTED`.

The coordinator decides a requested authorization by submitting a `decision` whose value is exactly `APPROVE` or `DENY` (uppercase); any other value is rejected as a malformed request with `ERR_INVALID_REQUEST`. Deciding is legal only while the authorization is `REQUESTED`; deciding one in any other state is rejected with `ERR_PA_NOT_REQUESTED`. To approve, the coordinator must supply `authorized_units_mg` greater than zero, which is recorded as the approved milligram ceiling and moves `status` to `APPROVED`; an approve decision without a positive `authorized_units_mg` is rejected as a malformed request with `ERR_INVALID_REQUEST`. A deny decision simply moves `status` to `DENIED`, a terminal state. Authorizations can be listed, optionally filtered by `patient_id`, and fetched by id.

The `consumed_units_mg` figure is a running total, never written directly by a client. It is the sum, over every `DrugOrder` linked to this authorization that has reached `ADMINISTERED`, of that order's `administered_dose_mg`. Each administer event adds the just-administered order's ordered dose to the total. The instant `consumed_units_mg` reaches or exceeds `authorized_units_mg`, the authorization auto-transitions from `APPROVED` to `EXHAUSTED`, and no further order may consume against it. `DENIED` and `EXHAUSTED` are the authorization's terminal states.

### 3.5. Planning and Activating a Treatment Cycle

A treatment cycle binds a patient to a protocol. A `Pharmacist` plans a cycle by supplying the `patient_id`, the `regimen_protocol_id` of a published protocol, and a `treatment_start_date` as an ISO calendar date (YYYY-MM-DD) anchoring cycle 1, day 1. The cycle is created in `PLANNED` status with `current_cycle_number` set to 1. The cycle `status` enumeration is `PLANNED`, `ACTIVE`, `ON_HOLD`, `COMPLETED`, and `ABANDONED`. Cycles can be listed, optionally filtered by `patient_id` or `regimen_protocol_id`, and fetched by id.

Activation moves a cycle from `PLANNED` to `ACTIVE` and is the moment dosing measurements freeze. A pharmacist activates a planned cycle only if two preconditions hold, and these two are the only guards on activation — the cycle's own `status` is not separately checked, so there is no distinct "cycle not PLANNED" rejection: the patient's `status` must be `ACTIVE`, or the activation is rejected with `ERR_PATIENT_NOT_ACTIVE`; and the protocol's `status` must be `PUBLISHED`, or it is rejected with `ERR_PROTOCOL_NOT_PUBLISHED`. These two preconditions are evaluated in that order, patient before protocol. On activation the system copies the patient's current `bsa_m2` into the cycle's `bsa_snapshot_m2` and the patient's current `gfr_ml_min` into the cycle's `gfr_snapshot_ml_min`, both frozen for the remainder of the cycle; sets `current_cycle_number` to 1; moves `status` to `ACTIVE`; and increments the cycle's `version` by 1. From this point every BSA-dosed order in the cycle reads `bsa_snapshot_m2` and every AUC-dosed order reads `gfr_snapshot_ml_min`, regardless of later patient edits.

### 3.6. The Cycle Calendar

The cycle calendar projects every order-set-item occurrence onto real calendar dates. Reading a cycle's calendar returns the complete projection as an `array`-typed response in one shot — it is not paginated and carries no `limit`, `offset`, `total_count`, or `has_more` pagination fields — listing, for each cycle number from 1 through the protocol's `total_cycles` and each order set item, the computed `scheduled_date`. The date is derived from the protocol's `cycle_length_days` (call it the cycle length) and the item's `day_offset`, anchored at the cycle's `treatment_start_date`: the scheduled date for cycle number n and an item with day offset d is the start date advanced by the quantity (n minus 1) times the cycle length, plus (d minus 1), days. For a start date of 2026-07-01, a cycle length of 21 days, an item with day offset 8, and cycle number 2, this is 2026-07-01 advanced by 21 plus 7, that is 28, days, giving 2026-07-29. Each calendar row carries the `cycle_number`, the `order_set_item_id`, the item's `drug_name` and `role`, and the computed `scheduled_date`. Rows are ordered by cycle number ascending, then by `day_offset` ascending, then by `sequence_index` ascending, with `created_at` ascending as the final tie-break — never by id. The calendar is a date-only projection at calendar-day granularity.

### 3.7. Creating a Drug Order: Dose, Vials, and Waste

Within an `ACTIVE` cycle, a `Pharmacist` creates a drug order against one of the protocol's order set items. The request carries the `treatment_cycle_id`, the `order_set_item_id` that defines the drug, role, dosing method, and vial size, an optional `prior_authorization_id` linking the order to a payer approval, and an optional `dose_reduction_pct` defaulting to 0 and constrained to the range 0 through 100. Creating an order requires the parent cycle to be `ACTIVE`; attempting it against any other cycle state is rejected with `ERR_CYCLE_NOT_ACTIVE`. A new order begins in `ORDERED` status. The order `status` enumeration is `ORDERED`, `PREPARED`, `VERIFIED`, `ADMINISTERED`, and `CANCELLED`. Drug orders can be listed — filterable by `treatment_cycle_id`, `order_set_item_id`, `prior_authorization_id`, `prepared_by_nurse_id`, or `verified_by_nurse_id` — and fetched by id.

At creation the system computes the entire dose-and-waste picture and stores it on the order. The computation runs in a fixed order: compute the base dose first, then apply the reduction, then round. The base dose depends on the item's dosing method. For a `BSA` item, the base is the item's `dose_per_m2` multiplied by the cycle's frozen `bsa_snapshot_m2`. For an `AUC` item, the base follows the Calvert renal formula: the item's `target_auc` multiplied by the quantity formed by taking the smaller of the cycle's frozen `gfr_snapshot_ml_min` and 125, then adding 25 — the glomerular filtration rate is capped at 125 before the addition, and AUC dosing never reads body surface area. For a `FLAT` item, the base is simply the item's `flat_dose_mg`. The reduction is then applied to this unrounded base: the reduced dose is the base multiplied by the quantity one minus `dose_reduction_pct` divided by 100. The `ordered_dose_mg` is that reduced figure rounded half-up to a whole number of milligrams.

From the ordered dose the system derives the supply chain. The `vials_drawn` is the ordered dose divided by the item's `vial_size_mg`, rounded up to the next whole vial. The `supplied_mg` is `vials_drawn` multiplied by `vial_size_mg`. The `waste_mg` is `supplied_mg` minus `ordered_dose_mg`. The `jw_modifier` flag is true exactly when `waste_mg` is greater than zero, marking the discarded single-use-vial drug as JW-billable. As a worked BSA example: with a dose per square meter of 175, a frozen body-surface snapshot of 1.82, no reduction, and a 50 mg vial, the base is 175 times 1.82 equals 318.5; with no reduction the reduced figure is 318.5; rounding 318.5 half-up gives an ordered dose of 319 mg; dividing 319 by 50 and rounding up gives 7 vials; supplied is 350 mg; waste is 31 mg; and the JW flag is true. As a worked AUC example: with a target AUC of 5, a frozen renal snapshot of 80, a 20 percent reduction, and a 150 mg vial, the base is 5 times the quantity 80 plus 25 equals 525; reduced by 20 percent gives 525 times 0.8 equals 420; the ordered dose is 420 mg; 420 divided by 150 rounded up is 3 vials; supplied is 450 mg; waste is 30 mg; and the JW flag is true. The order also carries an `administered_dose_mg` field that holds 0 until administration and is then set equal to `ordered_dose_mg`.

Specialty chemotherapy orders carry a referential safety gate at creation time, and the gate applies only to items whose `role` is `CHEMO` (a `PREMED` item is never gated). An item's drug is treated as a specialty drug requiring authorization exactly when at least one `PriorAuthorization` already exists for the cycle's patient and that item's `drug_name`, regardless of that authorization's status. The gate then resolves as follows. When a `prior_authorization_id` is supplied on a `CHEMO` order, it must reference an authorization for the same patient and the same `drug_name` whose `status` is `APPROVED`; if it does not match on all three counts, creation is rejected with `ERR_PRIOR_AUTH_REQUIRED`. When no `prior_authorization_id` is supplied on a `CHEMO` order, creation is rejected with `ERR_PRIOR_AUTH_REQUIRED` only if the drug qualifies as specialty by the existence rule above; a `CHEMO` drug for which no `PriorAuthorization` exists requires no linkage and is created freely.

### 3.8. Chairside: Prepare, the Double-Check, Reject, and Administer

The chairside lifecycle is where the two-nurse control lives. A `Nurse` prepares (mixes) an order, which is legal only when the parent cycle is `ACTIVE` (otherwise `ERR_CYCLE_NOT_ACTIVE`) and the order is in `ORDERED` status (otherwise `ERR_ORDER_NOT_ORDERED`). Preparation records the acting nurse's identity in `prepared_by_nurse_id` and advances the order from `ORDERED` to `PREPARED`.

A second nurse then verifies the prepared order, advancing it from `PREPARED` to `VERIFIED`. Verification is a four-precondition gate evaluated in this order. First, the order must be in `PREPARED` status, or the action is rejected with `ERR_ORDER_NOT_PREPARED`. Second, the acting nurse must be chemo-certified — their `is_chemo_certified` must be true — or the action is rejected with `ERR_NURSE_NOT_CERTIFIED` (403); an `X-User-ID` that does not resolve to any persisted `Nurse` is likewise treated as not chemo-certified and yields the same `ERR_NURSE_NOT_CERTIFIED` (403). Third, the acting nurse must differ from the recorded `prepared_by_nurse_id`, enforcing segregation of duties; a self-verification is rejected with `ERR_SAME_NURSE_VERIFICATION` (409). Fourth, the request carries a `recomputed_dose_mg` that the verifying nurse independently recomputes, and it must equal the order's stored `ordered_dose_mg`; any mismatch is rejected with `ERR_DOSE_VERIFICATION_MISMATCH` (409). When all four hold, the acting nurse's identity is recorded in `verified_by_nurse_id` and the order becomes `VERIFIED`.

A second nurse may instead reject a prepared order, sending it back for re-preparation. Rejection advances the order from `PREPARED` back to `ORDERED`. It requires the order to be in `PREPARED` status (otherwise `ERR_ORDER_NOT_PREPARED`) and requires the acting nurse to differ from `prepared_by_nurse_id` (otherwise `ERR_SAME_NURSE_VERIFICATION`); the same-nurse guard applies to rejection just as it does to verification. On rejection the `prepared_by_nurse_id` is cleared back to null and the order returns to `ORDERED`, ready for a fresh preparation.

Administration is the terminal clinical step, advancing a `VERIFIED` order to `ADMINISTERED`. A `Nurse` administers an order only when it is in `VERIFIED` status (otherwise `ERR_ORDER_NOT_VERIFIED`) and the parent cycle is `ACTIVE` (otherwise `ERR_CYCLE_NOT_ACTIVE`). If the order carries a `prior_authorization_id`, a fiscal check applies: the linked authorization must be `APPROVED` and its remaining headroom — `authorized_units_mg` minus `consumed_units_mg` — must be at least the order's `ordered_dose_mg`, or administration is rejected with `ERR_PRIOR_AUTH_INSUFFICIENT` (402). On success the order's `administered_dose_mg` is set to `ordered_dose_mg` and `status` becomes `ADMINISTERED`. If a prior authorization is linked, that order's ordered dose is then added to the authorization's `consumed_units_mg`; and if that addition makes `consumed_units_mg` reach or exceed `authorized_units_mg`, the authorization transitions from `APPROVED` to `EXHAUSTED`.

A non-terminal order — one in `ORDERED`, `PREPARED`, or `VERIFIED` — may be cancelled by a `Nurse` or a `Pharmacist`, moving it to `CANCELLED`; cancelling an already-terminal order (`ADMINISTERED` or `CANCELLED`) is rejected with `ERR_ORDER_TERMINAL`. Drug orders may also be cancelled implicitly by a cycle cascade, as described next; a cancelled order that had been `VERIFIED` reverses no reservation — its `administered_dose_mg` stays 0 and no authorization units are consumed.

### 3.9. Suspending, Resuming, Advancing, and Abandoning a Cycle

Toxicity and clinical judgment can suspend a running cycle. Placing an `ACTIVE` cycle `ON_HOLD` may be done explicitly by a `Nurse` or `Pharmacist`, or automatically by the system when a sufficiently severe toxicity event is recorded (see Section 3.11). The hold is legal only from `ACTIVE`; holding a cycle that is not `ACTIVE` is rejected with `ERR_CYCLE_NOT_ACTIVE`. A hold runs a two-step cascade. First, every drug order of the cycle that is in `ORDERED`, `PREPARED`, or `VERIFIED` is moved to `CANCELLED`; any such order that was `VERIFIED` reverses its reservation in the sense that its `administered_dose_mg` stays 0 and no prior-authorization consumption occurs. Second, every infusion appointment of the cycle in `SCHEDULED` or `CHECKED_IN` is moved to `CANCELLED`, releasing the chair and nurse intervals they held. The hold then moves the cycle `status` to `ON_HOLD` and increments the cycle's `version` by 1. Because that version bump invalidates any appointment booking composed against the pre-hold version, the optimistic-concurrency rule of Section 2.6 is what stops a stale booking from re-populating the just-cleared schedule.

Resuming returns an `ON_HOLD` cycle to `ACTIVE`. A `Pharmacist` resumes only when the cycle is `ON_HOLD` (otherwise `ERR_CYCLE_NOT_ON_HOLD`) and no unresolved toxicity event of grade 3 or higher remains open (otherwise `ERR_UNRESOLVED_TOXICITY`). Toxicity events carry no resolution flag and are never marked resolved, so any `ToxicityEvent` recorded against this cycle with a `ctcae_grade` of 3 or higher counts as an unresolved open event and blocks resume. Resume moves `status` to `ACTIVE` and increments `version` by 1.

Advancing the cycle moves the treatment forward one cycle or completes it. A `Pharmacist` advances a cycle that is `ACTIVE` (otherwise `ERR_CYCLE_NOT_ACTIVE`) and only when every drug order of the current cycle is in `ADMINISTERED` or `CANCELLED` (otherwise `ERR_UNRESOLVED_ORDERS`); because drug orders are not tagged with a cycle number, "every drug order of the current cycle" means every `DrugOrder` linked to this `TreatmentCycle` by `treatment_cycle_id`, irrespective of when it was created. The counter decides the branch with no separate input: when `current_cycle_number` is still below the protocol's `total_cycles`, the advance is a self-loop that increments `current_cycle_number` by 1 and leaves `status` at `ACTIVE`; when `current_cycle_number` already equals `total_cycles`, the advance instead moves `status` to `COMPLETED`. Either branch increments the cycle's `version` by 1. `COMPLETED` is a terminal state.

Abandoning ends a cycle prematurely. A `Pharmacist` abandons a cycle that is in `PLANNED`, `ACTIVE`, or `ON_HOLD`; abandoning a cycle already in a terminal state (`COMPLETED` or `ABANDONED`) is rejected with `ERR_CYCLE_TERMINAL`. Abandonment moves `status` to `ABANDONED`, then cascades exactly as a hold does over its children: every non-terminal drug order of the cycle is moved to `CANCELLED` and every non-terminal infusion appointment of the cycle is moved to `CANCELLED`, and the cycle's `version` increments by 1. `ABANDONED` is a terminal state.

### 3.10. Booking and Running Infusion Appointments

An infusion appointment reserves a chair-and-nurse interval for a cycle. A `Pharmacist` or `Nurse` books one by supplying the `treatment_cycle_id`, the `chair_id`, the `nurse_id` of the covering nurse, a `start_at` and `end_at` as ISO 8601 UTC instants with `end_at` strictly after `start_at`, an integer `acuity` weight in the range 1 through 5, and the `expected_treatment_cycle_version` carrying the cycle version the client last observed. A new appointment begins in `SCHEDULED` status; the appointment `status` enumeration is `SCHEDULED`, `CHECKED_IN`, `COMPLETED`, and `CANCELLED`. Appointments can be listed — filterable by `treatment_cycle_id`, `chair_id`, or `nurse_id` — and fetched by id.

Booking runs a sequence of guards beyond the body-validation and stale-version checks of Section 2. The chair must be `OPEN`; booking against a `CLOSED` chair is rejected with `ERR_CHAIR_CLOSED`. The chair must be free over the requested interval: the half-open span must not overlap any `SCHEDULED` or `CHECKED_IN` appointment already on that same chair, where overlap means the existing appointment starts strictly before the new `end_at` and the new `start_at` is strictly before the existing end, and adjacency where one ends exactly as the other begins is permitted; a clash is rejected with `ERR_CHAIR_DOUBLE_BOOKED`. The covering nurse must have acuity headroom: take every `SCHEDULED` or `CHECKED_IN` appointment already on that same nurse whose half-open interval overlaps the requested interval, sum their `acuity` values, add the new appointment's own `acuity`, and that concurrent load must not exceed the nurse's `max_acuity_load`. The rejection fires only when the load is strictly greater than `max_acuity_load` — a load exactly equal to the ceiling is permitted — and the rejection is `ERR_NURSE_ACUITY_EXCEEDED`.

Once booked, a `Nurse` checks the patient in, advancing the appointment from `SCHEDULED` to `CHECKED_IN`; check-in requires the appointment to be `SCHEDULED` (otherwise `ERR_APPOINTMENT_NOT_SCHEDULED`) and the parent cycle to be `ACTIVE` (otherwise `ERR_CYCLE_NOT_ACTIVE`). A nurse then completes a checked-in appointment, advancing it from `CHECKED_IN` to `COMPLETED`; completion requires the appointment to be `CHECKED_IN` (otherwise `ERR_APPOINTMENT_NOT_CHECKED_IN`). A non-terminal appointment — `SCHEDULED` or `CHECKED_IN` — may be cancelled by a `Nurse` or `Pharmacist`, moving it to `CANCELLED` and releasing its chair and nurse interval; cancelling an already-terminal appointment (`COMPLETED` or `CANCELLED`) is rejected with `ERR_APPOINTMENT_TERMINAL`. Appointments are also cancelled implicitly by a cycle hold or abandon cascade.

### 3.11. Toxicity Monitoring and Automatic Holds

Adverse reactions are recorded as toxicity events. A `Nurse` or `Pharmacist` records an event against a cycle by supplying the `treatment_cycle_id`, an optional `drug_order_id` naming the offending order when known, a `ctcae_grade` in the integer range 1 through 5, and a free-text `description`. The system sets the read-only `triggered_hold` flag to indicate whether this event caused an automatic cycle hold. Toxicity events can be listed — filterable by `treatment_cycle_id` or `drug_order_id` — and fetched by id.

The grade drives the safety response. When the recorded `ctcae_grade` is 3 or higher and the cycle is currently `ACTIVE`, recording the event automatically places the cycle `ON_HOLD` with the same two-step child cascade described in Section 3.9 — open drug orders cancelled, then open appointments cancelled — and increments the cycle's `version`; for that event `triggered_hold` is true. An event of grade 1 or 2, or any event recorded against a cycle that is not `ACTIVE`, does not move the cycle and leaves `triggered_hold` false. An unresolved open toxicity event of grade 3 or higher is exactly what blocks a later resume of the cycle with `ERR_UNRESOLVED_TOXICITY`, tying the monitoring workflow back to the resume gate of Section 3.9.

## 4. Endpoint Definitions

Creation of a new, distinct resource returns HTTP 201 Created. All lifecycle actions, state transitions, updates, and other modifications of an existing resource return HTTP 200 OK, as do all read operations. The request body, response body, and side effects of each endpoint are specified in the Section 3 narratives; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/infusion-center/patients` | Register a patient | Pharmacist |
| GET | `/infusion-center/patients` | List patients | Pharmacist, Nurse, PriorAuthCoordinator |
| GET | `/infusion-center/patients/{id}` | Get a patient | Pharmacist, Nurse, PriorAuthCoordinator |
| PATCH | `/infusion-center/patients/{id}` | Update patient height/weight/gfr | Pharmacist |
| POST | `/infusion-center/patients/{id}/mark-deceased` | Mark a patient deceased | Pharmacist |
| POST | `/infusion-center/regimen-protocols` | Create a DRAFT regimen protocol | Pharmacist |
| GET | `/infusion-center/regimen-protocols` | List regimen protocols | Pharmacist, Nurse, PriorAuthCoordinator |
| GET | `/infusion-center/regimen-protocols/{id}` | Get a regimen protocol | Pharmacist, Nurse, PriorAuthCoordinator |
| POST | `/infusion-center/regimen-protocols/{id}/publish` | Publish a protocol | Pharmacist |
| POST | `/infusion-center/order-set-items` | Attach an order set item to a DRAFT protocol | Pharmacist |
| GET | `/infusion-center/order-set-items` | List order set items | Pharmacist, Nurse, PriorAuthCoordinator |
| GET | `/infusion-center/order-set-items/{id}` | Get an order set item | Pharmacist, Nurse, PriorAuthCoordinator |
| POST | `/infusion-center/chairs` | Create an infusion chair/bay | Pharmacist |
| GET | `/infusion-center/chairs` | List chairs | Pharmacist, Nurse, PriorAuthCoordinator |
| GET | `/infusion-center/chairs/{id}` | Get a chair | Pharmacist, Nurse, PriorAuthCoordinator |
| POST | `/infusion-center/chairs/{id}/close` | Close a chair | Pharmacist |
| POST | `/infusion-center/nurses` | Create a nurse | Pharmacist |
| GET | `/infusion-center/nurses` | List nurses | Pharmacist, Nurse, PriorAuthCoordinator |
| GET | `/infusion-center/nurses/{id}` | Get a nurse | Pharmacist, Nurse, PriorAuthCoordinator |
| POST | `/infusion-center/prior-authorizations` | Open a specialty-drug prior authorization | PriorAuthCoordinator |
| GET | `/infusion-center/prior-authorizations` | List prior authorizations | Pharmacist, Nurse, PriorAuthCoordinator |
| GET | `/infusion-center/prior-authorizations/{id}` | Get a prior authorization | Pharmacist, Nurse, PriorAuthCoordinator |
| POST | `/infusion-center/prior-authorizations/{id}/decide` | Approve or deny a prior authorization | PriorAuthCoordinator |
| POST | `/infusion-center/treatment-cycles` | Plan a treatment cycle | Pharmacist |
| GET | `/infusion-center/treatment-cycles` | List treatment cycles | Pharmacist, Nurse, PriorAuthCoordinator |
| GET | `/infusion-center/treatment-cycles/{id}` | Get a treatment cycle | Pharmacist, Nurse, PriorAuthCoordinator |
| GET | `/infusion-center/treatment-cycles/{id}/calendar` | Get the computed cycle-day calendar | Pharmacist, Nurse, PriorAuthCoordinator |
| POST | `/infusion-center/treatment-cycles/{id}/activate` | Activate a planned cycle | Pharmacist |
| POST | `/infusion-center/treatment-cycles/{id}/hold` | Place an active cycle on hold | Nurse, Pharmacist |
| POST | `/infusion-center/treatment-cycles/{id}/resume` | Resume an on-hold cycle | Pharmacist |
| POST | `/infusion-center/treatment-cycles/{id}/advance-cycle` | Advance the cycle counter or complete | Pharmacist |
| POST | `/infusion-center/treatment-cycles/{id}/abandon` | Abandon a cycle | Pharmacist |
| POST | `/infusion-center/drug-orders` | Create a drug order on an active cycle | Pharmacist |
| GET | `/infusion-center/drug-orders` | List drug orders | Pharmacist, Nurse, PriorAuthCoordinator |
| GET | `/infusion-center/drug-orders/{id}` | Get a drug order | Pharmacist, Nurse, PriorAuthCoordinator |
| POST | `/infusion-center/drug-orders/{id}/prepare` | Prepare (mix) the order | Nurse |
| POST | `/infusion-center/drug-orders/{id}/verify` | Independently double-check and verify | Nurse |
| POST | `/infusion-center/drug-orders/{id}/reject` | Reject preparation, sending order back | Nurse |
| POST | `/infusion-center/drug-orders/{id}/administer` | Administer a verified order | Nurse |
| POST | `/infusion-center/drug-orders/{id}/cancel` | Cancel a non-terminal drug order | Nurse, Pharmacist |
| POST | `/infusion-center/infusion-appointments` | Book a chair+nurse interval for a cycle | Pharmacist, Nurse |
| GET | `/infusion-center/infusion-appointments` | List appointments | Pharmacist, Nurse, PriorAuthCoordinator |
| GET | `/infusion-center/infusion-appointments/{id}` | Get an appointment | Pharmacist, Nurse, PriorAuthCoordinator |
| POST | `/infusion-center/infusion-appointments/{id}/check-in` | Check a patient in | Nurse |
| POST | `/infusion-center/infusion-appointments/{id}/complete` | Complete an appointment | Nurse |
| POST | `/infusion-center/infusion-appointments/{id}/cancel` | Cancel an appointment | Nurse, Pharmacist |
| POST | `/infusion-center/toxicity-events` | Record a toxicity/reaction event | Nurse, Pharmacist |
| GET | `/infusion-center/toxicity-events` | List toxicity events | Pharmacist, Nurse, PriorAuthCoordinator |
| GET | `/infusion-center/toxicity-events/{id}` | Get a toxicity event | Pharmacist, Nurse, PriorAuthCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_PATIENT_NOT_FOUND` | 404 |
| `ERR_PROTOCOL_NOT_FOUND` | 404 |
| `ERR_ORDER_SET_ITEM_NOT_FOUND` | 404 |
| `ERR_CHAIR_NOT_FOUND` | 404 |
| `ERR_NURSE_NOT_FOUND` | 404 |
| `ERR_PRIOR_AUTH_NOT_FOUND` | 404 |
| `ERR_CYCLE_NOT_FOUND` | 404 |
| `ERR_DRUG_ORDER_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_TOXICITY_EVENT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_CYCLE_VERSION` | 412 |
| `ERR_NO_ORDER_SET_ITEMS` | 409 |
| `ERR_NO_CHEMO_ITEM` | 409 |
| `ERR_PROTOCOL_NOT_PUBLISHED` | 409 |
| `ERR_PATIENT_NOT_ACTIVE` | 409 |
| `ERR_CYCLE_NOT_ACTIVE` | 409 |
| `ERR_CYCLE_NOT_ON_HOLD` | 409 |
| `ERR_CYCLE_TERMINAL` | 409 |
| `ERR_UNRESOLVED_TOXICITY` | 409 |
| `ERR_UNRESOLVED_ORDERS` | 409 |
| `ERR_ORDER_NOT_ORDERED` | 409 |
| `ERR_ORDER_NOT_PREPARED` | 409 |
| `ERR_ORDER_NOT_VERIFIED` | 409 |
| `ERR_ORDER_TERMINAL` | 409 |
| `ERR_NURSE_NOT_CERTIFIED` | 403 |
| `ERR_SAME_NURSE_VERIFICATION` | 409 |
| `ERR_DOSE_VERIFICATION_MISMATCH` | 409 |
| `ERR_PA_NOT_REQUESTED` | 409 |
| `ERR_PRIOR_AUTH_REQUIRED` | 409 |
| `ERR_PRIOR_AUTH_INSUFFICIENT` | 402 |
| `ERR_CHAIR_DOUBLE_BOOKED` | 409 |
| `ERR_NURSE_ACUITY_EXCEEDED` | 409 |
| `ERR_CHAIR_CLOSED` | 409 |
| `ERR_APPOINTMENT_NOT_SCHEDULED` | 409 |
| `ERR_APPOINTMENT_NOT_CHECKED_IN` | 409 |
| `ERR_APPOINTMENT_TERMINAL` | 409 |
