# Blood Bank & Transfusion Service API — Product Requirements Document

## 1. Introduction

A hospital blood bank operates where transfusion medicine, perishable inventory logistics, and regulatory hemovigilance meet. Every red-cell unit, platelet dose, and plasma product that crosses the receiving dock carries a biological clock, a donor lineage, and a chain of custody; every unit that leaves the bank must be demonstrably compatible with the patient who receives it. The consequences of error are asymmetric — a misallocated unit costs money, but an incompatible transfusion costs lives — so the service must enforce its safety rules mechanically rather than relying on the diligence of individual operators.

This document specifies the Blood Bank & Transfusion Service API, the system of record for the bank's daily work: donor-unit inventory organized by product, blood group, and expiration; type-and-screen specimen processing under dual-technologist review; crossmatching against a combinatorial compatibility matrix whose direction reverses between red-cell and plasma products; order verification gated by shortage posture and massive-transfusion triage; issue and return under the thirty-minute rule; transfusion reaction reporting, investigation, and look-back recall; supplier replenishment with emergency ordering; par-level surveillance with rolling wastage triage; and transport cooler scheduling. All endpoints are mounted under the `/blood-bank` path prefix. The specification is written for the engineering team implementing the service, on behalf of the bench technologists, ordering physicians, supervisors, supplier coordinators, and quality officers whose work the API must faithfully serialize.

## 2. Global Specifications & System-Wide Principles

This section defines the envelope contracts, platform conventions, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operator's capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly five roles, spelled precisely as follows: `OrderingPhysician`, `BloodBankTechnologist`, `BloodBankSupervisor`, `SupplierCoordinator`, and `QualityOfficer`. A request whose role is not permitted to invoke the targeted endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

For each of the five roles — `OrderingPhysician`, `BloodBankTechnologist`, `BloodBankSupervisor`, `SupplierCoordinator`, and `QualityOfficer` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records the identifier on the artifacts the operator touches (for example as `ordering_physician_id` on a transfusion order, `verified_by_user_id` on an order verification or issue record, `resulted_by_user_id` and `validated_by_user_id` on a type-and-screen, `issued_by_user_id` on an issue, `reported_by_user_id` and `investigator_user_id` on a reaction, `activated_by_physician_id` on a protocol activation, `checked_out_by_user_id` on a cooler checkout, and `recorded_by_user_id` on a wastage record), but it never compares `X-User-ID` against any entity's `id`. Segregation-of-duties checks in this system compare two operator identifiers against each other — the person who performed an earlier step versus the caller attempting the later step — never an operator against a patient or unit record.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, accepts a minimum of 1, and is bounded above at 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless a list endpoint states otherwise, resources are returned sorted by their creation timestamp in ascending order. The `meta` object of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Maintenance Sweep

All temporal reasoning in the system — the 72-hour specimen validity, the four-hour transfusion start window, the twenty-four-hour acknowledgement window, the thirty-minute return rule, every expiration timestamp, and every cooler restock buffer — evaluates against a server-held logical clock, never the host wall clock. Before any operator intervenes, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `BloodBankSupervisor` may advance or reposition the clock through a test-driving capability that accepts a target instant `to_iso8601` and answers with the now-current `current_utc`; this capability exists so that time-dependent behavior can be exercised deterministically.

A second supervisor-only capability, the **maintenance sweep**, runs all time-based maintenance at the current logical time in one call. The sweep expires every type-and-screen whose validity has lapsed (current time at or past its `expires_at`) and fires the associated expiry cascade described in §3.1; expires every compatible crossmatch whose reservation window has closed, releasing its reserved unit; expires every blood unit whose `expires_at` has been reached — units in `ISSUED` status are exempt, because the four-hour start window and the thirty-minute return rule govern them instead — creating an `EXPIRED` wastage record for each; releases cooler occupancy whose planned window has lapsed and advances restocking coolers whose `restock_until` has passed back to availability; and recomputes every bucket posture. The sweep's response tallies its work in five counters: `ts_expired_count`, `crossmatches_expired_count`, `units_expired_count`, `coolers_restocked_count`, and `orders_held_count`.

### 2.5. Common Resource Properties and the Append-Only Wastage Log

With one deliberate exception, every resource in the API carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, captured when the resource is first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp refreshed on every mutation of the resource, including system-driven recomputes.
- **`version` (integer):** a system-managed integer that increments by one on every mutation, available for optimistic concurrency control where §2.8 declares it.

The exception is the **WastageRecord**, an append-only event log entry that carries only `id` and `created_at`; both `updated_at` and `version` are absent from it by design, since a wastage record is written once and never modified.

### 2.6. Blood Components, Demand Buckets, and Typing Vocabulary

Six product types circulate through the bank: `RBC` (packed red cells), `WHOLE_BLOOD`, `PLT_APHERESIS` (single-donor apheresis platelets), `PLT_POOL` (pooled platelets), `FFP` (fresh frozen plasma), and `CRYO` (cryoprecipitate). For compatibility purposes these divide into two classes that behave under opposite ABO logic: the **red-cell class** comprises `RBC` and `WHOLE_BLOOD`, while the **plasma class** comprises `FFP`, `CRYO`, `PLT_APHERESIS`, and `PLT_POOL`. ABO groups are drawn from `O`, `A`, `B`, and `AB`; Rh types are `POS` or `NEG`. Where a patient's typing is not yet established, both fields take the sentinel value `UNKNOWN`.

Inventory, policy, and gating all key on the **demand bucket** — a triple of product type, ABO group, and Rh type rendered as a string such as `RBC:O:NEG`. Patients may carry special handling requirements drawn from `IRRADIATED`, `CMV_NEGATIVE`, and `WASHED`; every unit issued to such a patient must satisfy every listed requirement. Units may in turn be tested antigen-negative for a panel drawn from the twelve antigens `K`, `k`, `C`, `c`, `E`, `e`, `Jka`, `Jkb`, `Fya`, `Fyb`, `S`, and `s`, and identified patient antibodies are recorded with names such as anti-K or anti-Jka.

### 2.7. Numeric Precision, Rounding, and Monetary Conventions

Monetary values are integer cent counts, never floating-point numbers; supplier-order cost estimation rounds half-up at exactly two pinned points in its pipeline (each line first, then once on the emergency-adjusted total), as §3.2 spells out. The rolling wastage rate is a ratio rounded half-up to four decimal places. Timestamp arithmetic — shelf lives, reservation windows, derived-product clocks — is exact to the second with no rounding. Unit counts, thresholds, and tallies are integers. Numeric values travel in API bodies as numbers, not strings.

### 2.8. Optimistic Concurrency Control

Two write endpoints carry an optimistic-concurrency contract, and no others do. Creating a type-and-screen specimen requires the request to carry `expected_patient_version`, the `version` of the target patient as last observed by the caller; if the patient's current `version` has advanced past that value — for instance because another technologist has just collected or validated a specimen for the same patient, each of which moves the patient's summary and version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from typing against a patient record it has not observed. Updating a par-level policy requires `expected_policy_version`, the policy's `version` as last observed; if another supervisor has tightened or loosened the same bucket's thresholds in the meantime, the update is rejected with `ERR_STALE_VERSION` (HTTP 412) so a stale threshold set cannot silently overwrite a newer configuration. Endpoints not named in this subsection accept no version field at all.

### 2.9. Request Validation Pipeline and Identifier Resolution

Every request passes through a fixed validation pipeline, and when several rules are violated at once the earliest stage in this order wins. First, header presence (§2.1's `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, role permission (`ERR_UNAUTHORIZED_ROLE`); third, path-identifier existence, validated left to right — an unmatched route or an unknown path id yields a resource-specific 404: `ERR_PATIENT_NOT_FOUND` for a patient, `ERR_SUPPLIER_NOT_FOUND` for a supplier, `ERR_SUPPLIER_ORDER_NOT_FOUND` for a supplier order, `ERR_UNIT_NOT_FOUND` for a blood unit, `ERR_TS_NOT_FOUND` for a type-and-screen, `ERR_ORDER_NOT_FOUND` for a transfusion order, `ERR_CROSSMATCH_NOT_FOUND` for a crossmatch, `ERR_ISSUE_NOT_FOUND` for an issue record, `ERR_REACTION_NOT_FOUND` for a reaction, `ERR_RECALL_NOT_FOUND` for a recall case, `ERR_WASTAGE_RECORD_NOT_FOUND` for a wastage record, `ERR_POLICY_NOT_FOUND` for a par-level policy, `ERR_COOLER_NOT_FOUND` for a transport cooler, `ERR_CHECKOUT_NOT_FOUND` for a cooler checkout, or `ERR_MTP_NOT_FOUND` for a protocol activation — so that, for example, a request naming a nonexistent recall case id is rejected with `ERR_RECALL_NOT_FOUND` before any nested reference is examined. Fourth, request-schema conformance — required fields present, types correct, enum values within their declared sets, integer ranges respected — under `ERR_INVALID_REQUEST` (HTTP 400). Fifth, existence of foreign-key references carried in the body (`patient_id`, `supplier_id`, `order_id`, `unit_id`, `issue_record_id`, `cooler_id`, and the recall's scoping `unit_id`), each unresolved reference rejected with the generic `ERR_NOT_FOUND` (HTTP 404). Sixth, optimistic concurrency where declared (`ERR_STALE_VERSION`). Seventh, the from-state precondition of the invoked state-machine transition, each with its own 409 error enumerated in §3.

Once structural checks pass, the business rules evaluate in a fixed order: unit compatibility for an explicitly selected unit (`ERR_UNIT_INCOMPATIBLE`); segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); the two-specimen rule (`ERR_SECOND_SPECIMEN_REQUIRED`); emergency-release eligibility and justification (`ERR_EMERGENCY_RELEASE_NOT_ALLOWED`, `ERR_EMERGENCY_JUSTIFICATION_REQUIRED`); ordering-physician identity on emergency acknowledgement (`ERR_NOT_ORDERING_PHYSICIAN`); the ban on future timestamps (`ERR_SPECIMEN_TIME_INVALID`); the four-hour transfusion start window (`ERR_TRANSFUSION_START_WINDOW_LAPSED`); the twenty-four-hour acknowledgement window (`ERR_EMERGENCY_ACK_WINDOW_LAPSED`); cooler window validity and conflicts (`ERR_CHECKOUT_WINDOW_INVALID`, `ERR_COOLER_WINDOW_CONFLICT`); duplicate specimen collection (`ERR_DUPLICATE_SPECIMEN`); policy bucket uniqueness (`ERR_POLICY_BUCKET_DUPLICATE`); threshold ordering (`ERR_THRESHOLD_ORDER_INVALID`); recall scope consistency (`ERR_RECALL_SCOPE_INVALID`); protocol uniqueness per patient (`ERR_MTP_ALREADY_ACTIVE`); the order-fulfillment ceiling at crossmatch creation (`ERR_ORDER_FULLY_CROSSMATCHED`); the issue quota (`ERR_ORDER_ISSUE_QUOTA_MET`); over-receipt (`ERR_OVER_RECEIPT`); unit-number uniqueness (`ERR_DUPLICATE_UNIT_NUMBER`); supplier standing (`ERR_SUPPLIER_SUSPENDED`); notification eligibility (`ERR_ISSUE_NOT_IMPLICATED`, `ERR_ISSUE_ALREADY_NOTIFIED`); the completion gates on notifications, linked recalls, and workups (`ERR_NOTIFICATIONS_PENDING`, `ERR_RECALL_INCOMPLETE`, `ERR_REACTION_WORKUP_MISSING`); the wastage review gate (`ERR_WASTAGE_REVIEW_REQUIRED`); the shortage admission gates (`ERR_BUCKET_CRITICAL_ELECTIVE_BLOCKED`, `ERR_BUCKET_SHORTAGE_MTP_PRIORITY`); and finally the auto-selector's empty-pool check (`ERR_NO_COMPATIBLE_UNIT`).

### 2.10. Inventory Posture Ladders and Demand Gating

Every demand bucket with an `ACTIVE` par-level policy is continuously graded on a four-rung posture ladder: `NORMAL`, `WATCH`, `SHORTAGE`, and `CRITICAL`. The rung derives from the bucket's **usable unit count** — units of the bucket's product type, ABO group, and Rh type that sit in `AVAILABLE` status and whose `expires_at` lies strictly beyond the current time plus the policy's `min_shelf_life_hours` horizon. If that count is at or below the bucket's `critical_threshold` the posture is `CRITICAL`; otherwise, if at or below the `shortage_threshold`, `SHORTAGE`; otherwise, if at or below the `watch_threshold`, `WATCH`; otherwise `NORMAL`. The boundary is inclusive — a count exactly equal to the critical threshold grades `CRITICAL`. A bucket with no `ACTIVE` policy is treated as `NORMAL` everywhere and admits no gating.

Two flavors of posture exist. The **physical posture** counts only stock on the shelf, as above, and it is the flavor that gates order verification. The **prospective posture** adds inbound supply: undelivered line remainders (ordered quantity minus received quantity) on supplier orders in `SUBMITTED`, `ACKNOWLEDGED`, or `RECEIVING` status whose `expected_delivery_at` is set and falls within the next twenty-four hours, counted for lines matching the bucket. The same threshold ladder is then applied to the sum of usable and inbound units, so a bucket with one usable unit and four inbound units can be physically `CRITICAL` yet prospectively `NORMAL` on identical shelf data. Postures are recomputed on every inventory mutation, every sweep, and every policy create or update.

Posture feeds two admission gates at order verification, detailed in §3.3, and the wastage-rate gate on supplier-order submission, detailed in §3.2 and §3.8.

### 2.11. Quarantine Holds and Cross-Entity Cascades

Several distinct events converge on one holding mechanism. A blood unit placed under quarantine hold moves to `QUARANTINED_HOLD`, remembers the state it occupied at hold time in `hold_origin_state` (one of `QUARANTINED`, `AVAILABLE`, `RESERVED`, or `ISSUED`, and null when not held), and records why in `hold_reason` (one of `REACTION_PRECAUTION`, `RECALL`, or `SUPPLIER_SUSPENSION`, null when not held). The three reasons have different exits: supplier reinstatement releases only `SUPPLIER_SUSPENSION` holds, always landing the unit on `AVAILABLE` regardless of its origin; a concluded reaction investigation and a closed recall dispose of their held units per §3.7; and recall holds never auto-release.

More broadly, the system maintains consistency by letting state changes propagate without waiting for a client to touch each affected resource. A type-and-screen expiring puts its patient's unfulfilled orders on hold; a supplier suspension quarantine-holds that supplier's live inventory and cancels the crossmatches pinning it; a recall quarantine does the same for implicated units; a returned or stopped issue decrements its order's counters and can revert the order's state. Each such automatic reconciliation mutates the affected resource normally, refreshing its `updated_at` and incrementing its `version`.

## 3. Business Logic & Workflows

### 3.1. Patient Registration and the Type & Screen Lifecycle

A `BloodBankTechnologist` or `BloodBankSupervisor` registers a **Patient** blood-bank record with a medical record number `mrn` (unique across all patients), the patient's `full_name`, and `date_of_birth` in YYYY-MM-DD form; an optional `special_requirements` array defaults to empty and may list any subset of `IRRADIATED`, `CMV_NEGATIVE`, and `WASHED`. Typing fields are entirely computed: a fresh patient has `current_abo_type` and `current_rh_type` of `UNKNOWN`, `antibody_status` of `UNKNOWN`, an empty `identified_antibodies`, `abo_confirmed` false, `has_active_type_and_screen` false, `active_mtp` false, and `total_units_transfused` of zero. The patient list endpoint accepts the filters `mrn`, `current_abo_type`, and `has_active_type_and_screen`.

Typing begins when a `BloodBankTechnologist` collects a **TypeAndScreen** specimen, supplying the `patient_id`, the `specimen_collected_at` timestamp, and — per §2.8 — `expected_patient_version`. The collection timestamp must not lie in the future, on pain of `ERR_SPECIMEN_TIME_INVALID` (HTTP 400), and it must differ from the `specimen_collected_at` of every other non-`REJECTED` type-and-screen belonging to the same patient, on pain of `ERR_DUPLICATE_SPECIMEN` (HTTP 409). Collection lands the record in `COLLECTED` status, computes its `expires_at` as exactly seventy-two hours (three days) after `specimen_collected_at`, and — because a pending specimen changes the clinical picture — increments the patient's `version` by one. The specimen list endpoint accepts the filters `patient_id` and `status`.

Result entry moves the specimen from `COLLECTED` to `RESULTED`; attempting it on a specimen in any other status is rejected with `ERR_TS_NOT_COLLECTED`. The bench technologist records `abo_result` (one of `O`, `A`, `B`, `AB`), `rh_result` (`POS` or `NEG`), and `antibody_screen` (`NEGATIVE` or `POSITIVE`); when the screen is `POSITIVE`, a non-empty `antibody_identifications` array (entries such as anti-K) is mandatory, and its absence draws `ERR_ANTIBODY_DETAIL_REQUIRED` (HTTP 422). The system stamps `resulted_at` and captures the acting technologist in `resulted_by_user_id`.

A second technologist then **validates** the result, moving the specimen from `RESULTED` to `ACTIVE`. Validation on a specimen not in `RESULTED` fails with `ERR_TS_NOT_RESULTED`, and — the first of this system's segregation-of-duties rules — the validator's `X-User-ID` must differ from `resulted_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Validation is the moment the patient's typing is recomputed: any other `ACTIVE` specimen of the same patient is superseded to `SUPERSEDED`; `current_abo_type`, `current_rh_type`, `antibody_status`, and `identified_antibodies` are copied from the newly validated specimen (the most recently validated by `validated_at`), `has_active_type_and_screen` becomes true, `validated_at` and `validated_by_user_id` are stamped, and the patient's `version` increments. Validation also latches the **two-specimen ABO confirmation**: if another type-and-screen of the same patient exists in `ACTIVE`, `SUPERSEDED`, or `EXPIRED` status with the same `abo_result` but a different `specimen_collected_at`, the patient's `abo_confirmed` flips to true — and once latched it never auto-clears, even if both specimens later expire. A specimen that is mislabeled or hemolyzed may instead be rejected from `COLLECTED` with a recorded `reject_reason`, settling in `REJECTED`; the same `ERR_TS_NOT_COLLECTED` guards that transition's from-state.

Time kills specimens. A type-and-screen counts as active only while the current time is strictly before its `expires_at`; the maintenance sweep moves an `ACTIVE` specimen whose time has come to `EXPIRED`. When that expiry strips a patient of their last `ACTIVE` specimen, `has_active_type_and_screen` falls to false and the **T&S-expiry cascade** fires across the patient's open work: every `COMPATIBLE` crossmatch on the patient's orders moves to `EXPIRED`, each releasing its `RESERVED` unit back to `AVAILABLE`; every `PENDING` crossmatch on those orders moves to `CANCELLED`; and every transfusion order of the patient sitting in `AWAITING_CROSSMATCH`, `READY`, or `PARTIALLY_ISSUED` drops to `ON_HOLD`, with bucket postures recomputed throughout. The patient's `current_abo_type`, `current_rh_type`, and `antibody_status` are retained as historical facts after expiry — they describe what was last validated, not what is currently valid. The terminal states of the type-and-screen machine are `EXPIRED`, `SUPERSEDED`, and `REJECTED`.

### 3.2. Suppliers, Replenishment Orders, and Unit Intake

The bank buys from registered **Supplier** organizations. A `BloodBankSupervisor` registers a supplier with a `name`, a regulatory `license_number` (unique), and an optional `default_lead_time_hours` that defaults to 48 hours; the record opens in `ACTIVE` status with `suspended_at` null. Suppliers may be listed filtered by `status`.

Suspension is a supervisory action with teeth. Suspending an `ACTIVE` supplier — any other from-state draws `ERR_SUPPLIER_SUSPENDED` — stamps `suspended_at`, records the supplied `reason` in `suspend_reason`, moves the supplier to `SUSPENDED`, and cascade-holds every one of its blood units in `QUARANTINED`, `AVAILABLE`, or `RESERVED`: each goes to `QUARANTINED_HOLD` with `hold_reason` of `SUPPLIER_SUSPENSION` and its prior state preserved in `hold_origin_state`. A held `RESERVED` unit's `COMPATIBLE` crossmatch is cancelled, and the order recompute that follows can drop a `READY` order back to `AWAITING_CROSSMATCH` when fulfillment falls below the requested count. Reinstating a `SUSPENDED` supplier (again, any other from-state draws `ERR_SUPPLIER_SUSPENDED`) releases exactly those holds: every `QUARANTINED_HOLD` unit whose `hold_reason` is `SUPPLIER_SUSPENSION` returns to `AVAILABLE` — always `AVAILABLE`, even for a unit that was `RESERVED` when held, because its crossmatch was already cancelled at hold time — the hold origin is cleared, `suspended_at` returns to null, and bucket postures are recomputed.

Replenishment runs through **SupplierOrder** records, created by a `SupplierCoordinator` or `BloodBankSupervisor` against a `supplier_id` with a `lines` array — each line naming `product_type`, `abo_type`, `rh_type`, and a `quantity` that must be a positive integer — plus an optional `is_emergency` flag (defaulting to false) and an optional `expected_delivery_at` that drives prospective-posture inclusion per §2.10. The order opens in `DRAFT`. At creation the server computes `estimated_cost_cents`, and because the lines are immutable afterward it is never recomputed. The estimation prices each product at a fixed per-unit rate in cents — `RBC` at 21,997, `WHOLE_BLOOD` at 34,995, `PLT_APHERESIS` at 54,995, `PLT_POOL` at 47,995, `FFP` at 7,995, and `CRYO` at 6,495 — and grants a volume discount on the whole order: ten percent when the lines total at least fifty units, five percent when they total at least twenty, and nothing below that. The rounding order is pinned: each line's cost — its unit price times its quantity times one-minus-the-discount — is rounded half-up to whole cents first, the rounded lines are summed into a subtotal, and only then, for an emergency order, is a twenty-five percent surcharge applied to that subtotal with a single half-up rounding. The supplier-order list accepts the filters `supplier_id` and `status`.

Submission moves a `DRAFT` order to `SUBMITTED` (any other from-state: `ERR_SO_NOT_SUBMITTABLE`) and requires the supplier to be `ACTIVE` (`ERR_SUPPLIER_SUSPENDED` otherwise). A **wastage review gate** guards submission: when a `SupplierCoordinator` — but not a `BloodBankSupervisor`, who is exempt — submits a non-emergency order and any bucket named in its lines currently carries a rolling wastage rate of 0.05 or more (see §3.8), the submission is rejected with `ERR_WASTAGE_REVIEW_REQUIRED` (HTTP 409), forcing a supervisor's eyes onto a bleeding bucket before more stock is ordered into it. An emergency order (`is_emergency` true) acknowledges itself within the same call, advancing straight through to `ACKNOWLEDGED`; a routine order waits for an explicit acknowledgement, which moves `SUBMITTED` to `ACKNOWLEDGED` or fails with `ERR_SO_NOT_ACKNOWLEDGEABLE`. Cancellation is available from `DRAFT`, `SUBMITTED`, or `ACKNOWLEDGED`, settling the order in `CANCELLED`; from any other state the attempt meets `ERR_SO_NOT_CANCELLABLE`.

Receipt is where inventory is born. Receiving against an order in `ACKNOWLEDGED` or `RECEIVING` — otherwise `ERR_SO_NOT_RECEIVABLE` — accepts a `units` payload of unit descriptors and creates one **BloodUnit** per descriptor, opening each in `QUARANTINED`. The receipt enforces three intake rules: each descriptor's `product_type`, `abo_type`, and `rh_type` must match a line on the order and the cumulative received quantity per line must never exceed the ordered quantity, else `ERR_OVER_RECEIPT` (HTTP 422); each `unit_number` (the supplier-assigned ISBT identifier) must be globally unique across every unit ever received, else `ERR_DUPLICATE_UNIT_NUMBER` (HTTP 409); and no `collected_at`, `thawed_at`, or `pooled_at` may lie in the future, else `ERR_SPECIMEN_TIME_INVALID`. Each descriptor carries the new unit's `unit_number`, `donor_id` (an opaque donor identifier, not an entity — the look-back scope key), `lot_number` (the recall scope key), `product_type`, `abo_type`, `rh_type`, a strictly positive `volume_ml`, `collected_at`, and optionally `thawed_at` (for thawed `FFP` or `CRYO`, starting the derived-product clock), `pooled_at` (for `PLT_POOL`, starting the four-hour pool clock), an `antigen_negative` array (default empty, entries drawn from the twelve-antigen panel of §2.6), the booleans `irradiated`, `cmv_negative`, and `washed` (each defaulting to false), and an optional `derived_from_unit_id` self-reference for split or aliquot units. The created unit's `supplier_order_id` and `supplier_id` are denormalized from the receipt.

Every received unit's `expires_at` is computed at intake as the earlier of two clocks. The fixed clock adds a class shelf life to `collected_at`: 1,008 hours (forty-two days) for `RBC`, 840 hours (thirty-five days) for `WHOLE_BLOOD`, 120 hours (five days) for either platelet product, and 8,760 hours (one year) for `FFP` or `CRYO`. The derived clock runs only when a thaw or pool timestamp is supplied: a thawed `FFP` unit expires twenty-four hours after `thawed_at`, a thawed `CRYO` unit six hours after, and a pooled platelet four hours after `pooled_at`; when both a thaw and a pool are present the derived clock takes whichever comes first. An `FFP` unit collected on 2026-08-01 and thawed on 2026-08-10 at 06:00 therefore expires on 2026-08-11 at 06:00 even though its frozen shelf life runs into 2027 — same `collected_at`, different `expires_at`. Receipt updates the order's `received_summary` (per-line `received_qty` alongside each line's `product_type`, `abo_type`, and `rh_type`) and `total_units_received`; the first receipt moves the order to `RECEIVING`, and when every line stands fully received the order auto-closes to `CLOSED` within the same call. A supervisor or coordinator may also close a `RECEIVING` order manually (any other state: `ERR_SO_NOT_CLOSABLE`); closure sets `backordered` true when any line closed short of its ordered quantity. `CLOSED` and `CANCELLED` are terminal.

Units in intake quarantine await a bench decision. Releasing a `QUARANTINED` unit to `AVAILABLE` — a `BloodBankTechnologist` action requiring the supplier to be `ACTIVE` (`ERR_SUPPLIER_SUSPENDED` when suspended) and the unit to be in `QUARANTINED` (`ERR_UNIT_NOT_RELEASABLE` otherwise) — recomputes the bucket posture. A technologist may instead reject the unit at intake with a recorded `reason` persisted in `intake_reject_reason`, moving it from `QUARANTINED` to terminal `REJECTED` (`ERR_UNIT_NOT_REJECTABLE` from any other state). A `BloodBankSupervisor` may manually discard a unit in `AVAILABLE`, `QUARANTINED`, or `QUARANTINED_HOLD` — elsewhere `ERR_UNIT_NOT_DISCARDABLE` — optionally attaching a `note`; the unit settles in `DISCARDED` and a wastage record with reason `MANUAL` is written, with posture and wastage rate recomputed. Units that outlive their `expires_at` while `AVAILABLE`, `QUARANTINED`, `RESERVED`, or `QUARANTINED_HOLD` are moved to `EXPIRED` by the sweep with an `EXPIRED` wastage record each; when the expiring unit was `RESERVED`, its `COMPATIBLE` crossmatch moves to `EXPIRED` as well, decrementing the order's `units_crossmatched` and reverting a `READY` order to `AWAITING_CROSSMATCH` if fulfillment has fallen short, while the unit itself settles in `EXPIRED` rather than returning to the shelf. Units in `ISSUED` are exempt from the expiry sweep. The blood-unit list endpoint filters by `status`, `product_type`, `abo_type`, `rh_type`, `supplier_id`, `supplier_order_id`, `donor_id`, `lot_number`, `derived_from_unit_id`, `unit_number`, and `expires_before`.

### 3.3. Transfusion Orders and Verification Under Scarcity

An `OrderingPhysician` places a **TransfusionOrder** with the `patient_id`, the `product_type`, a `units_requested` count from 1 to 20 inclusive, an `urgency` of `ROUTINE`, `URGENT`, or `EMERGENCY`, and a clinical `indication_code`. The order opens in `PENDING_VERIFICATION` with `ordering_physician_id` captured from the caller's `X-User-ID`. Three counters track fulfillment as work proceeds: `units_crossmatched` counts the order's crossmatches in `COMPATIBLE`; `units_issued_net` counts its issue records in `ISSUED`, `TRANSFUSION_STARTED`, or `TRANSFUSED`; and `units_transfused` counts those in `TRANSFUSED`. The order's **fulfillment** is the sum of `units_crossmatched` and `units_issued_net`. The order list endpoint filters by `patient_id`, `status`, `product_type`, and `urgency`.

Verification is the technologist's gate, and it enforces its checks in the order given by §2.9's pipeline. The order must stand in `PENDING_VERIFICATION` (`ERR_ORDER_NOT_VERIFIABLE`); the verifying technologist's `X-User-ID` must differ from `ordering_physician_id`, the segregation-of-duties rule for ordering (`ERR_SEGREGATION_OF_DUTIES`); and the patient must hold an `ACTIVE` type-and-screen — unless the order's `urgency` is `EMERGENCY`, which alone may proceed untyped — else `ERR_TS_NOT_ACTIVE`. Two scarcity gates then apply to the order's **demand bucket**, a triple of the form `product_type:ABO:Rh` (for example `RBC:O:NEG`) evaluated from the patient's `current_abo_type` and `current_rh_type` at verify time, with `UNKNOWN` typing mapped to `O:NEG` for red-cell-class products and `AB:NEG` for plasma-class products. First, if an `ACTIVE` par-level policy exists for that bucket and its current posture is `CRITICAL`, a `ROUTINE` order is rejected with `ERR_BUCKET_CRITICAL_ELECTIVE_BLOCKED` — elective draws on a critical bucket are refused outright. Second, if any patient anywhere has an `ACTIVATED` massive transfusion protocol and the bucket's posture is `SHORTAGE` or `CRITICAL`, a `ROUTINE` order is rejected with `ERR_BUCKET_SHORTAGE_MTP_PRIORITY`, reserving strained stock for the protocol. `URGENT` and `EMERGENCY` orders pass both gates.

A successful verify stamps `verified_by_user_id` and `verified_at`, snapshots the patient's `special_requirements` into `special_requirements_snapshot`, and computes three derived fields: `requires_crossmatch`, true exactly when the ordered product is `RBC` or `WHOLE_BLOOD`; `type_restriction`, set to `O_ONLY` for red-cell-class or `AB_ONLY` for plasma-class products when the order was verified without an `ACTIVE` type-and-screen and otherwise `NONE`; and the `demand_bucket` described above. The order's stay in `VERIFIED` is transient — within the same call it auto-advances to `AWAITING_CROSSMATCH` when a crossmatch is required, or straight to `READY` when it is not. A technologist who cannot verify the order instead rejects it from `PENDING_VERIFICATION` with a `rejection_reason`, settling it in terminal `REJECTED`; any other from-state draws `ERR_ORDER_NOT_REJECTABLE`.

From there the order rides its counters. When fulfillment reaches `units_requested`, an `AWAITING_CROSSMATCH` order advances to `READY`. The first successful issue — `units_issued_net` reaching at least one — moves `READY` to `PARTIALLY_ISSUED`. Events that erode fulfillment run it backward: a crossmatch cancellation or expiry that drops fulfillment below `units_requested` reverts `READY` to `AWAITING_CROSSMATCH`; a return or stop that drops fulfillment below the requested count reverts `PARTIALLY_ISSUED` to `AWAITING_CROSSMATCH`, while one that merely brings `units_issued_net` to zero with fulfillment still satisfied returns it to `READY`. When `units_transfused` reaches `units_requested`, a `PARTIALLY_ISSUED` order settles in terminal `COMPLETED`. The T&S-expiry cascade (§3.1) drops any of `AWAITING_CROSSMATCH`, `READY`, or `PARTIALLY_ISSUED` to `ON_HOLD`.

An `ON_HOLD` order can be **reactivated** by a technologist once the patient again holds an `ACTIVE` type-and-screen: the order must be `ON_HOLD` (`ERR_ORDER_NOT_REACTIVATABLE` otherwise) and the patient's `has_active_type_and_screen` true (`ERR_TS_NOT_ACTIVE` otherwise). Reactivation's target state is derived from the live counters rather than chosen by the caller: fulfillment still short of `units_requested` lands in `AWAITING_CROSSMATCH`; fulfillment satisfied with nothing currently issued lands in `READY`; and at least one unit issued with `units_transfused` still below the request lands in `PARTIALLY_ISSUED`. Finally, the ordering physician may cancel the order — with an optional `cancel_reason` — from any of `PENDING_VERIFICATION`, `AWAITING_CROSSMATCH`, `READY`, `PARTIALLY_ISSUED`, or `ON_HOLD` (anything else: `ERR_ORDER_NOT_CANCELLABLE`). Cancellation moves every `PENDING` or `COMPATIBLE` crossmatch on the order to `CANCELLED` and releases each `RESERVED` unit back to `AVAILABLE`; issue records already in `ISSUED` or `TRANSFUSION_STARTED` are deliberately unaffected and must be returned or completed independently.

### 3.4. Compatibility Decisions and the Crossmatch Workflow

A **Crossmatch** pairs an order with a candidate unit. A `BloodBankTechnologist` creates one with an `order_id` and, optionally, a `unit_id`; the record opens in `PENDING`, denormalizes `patient_id` from the order, and computes its `method` — `ELECTRONIC` exactly when the patient's `abo_confirmed` is latched and their `antibody_status` is `NEGATIVE`, and `SEROLOGIC_AHG` otherwise. Creation is refused once the order is already fulfilled: `units_crossmatched` plus `units_issued_net` must be below `units_requested`, else `ERR_ORDER_FULLY_CROSSMATCHED` (HTTP 409). When `unit_id` is omitted the server auto-selects a unit per the FEFO selector below and sets `auto_selected` true; when the selector's candidate pool is empty the create is rejected with `ERR_NO_COMPATIBLE_UNIT` (HTTP 409). The crossmatch list endpoint filters by `order_id`, `unit_id`, `patient_id`, and `status`.

Whether a specific unit may serve a specific patient and order is settled by the **unit compatibility decision**, a fixed seven-step evaluation invoked at crossmatch creation with an explicit `unit_id`, at issue creation with an explicit `unit_id`, and inside the selector as an eligibility filter. Step one fixes the product class: red-cell class for `RBC` and `WHOLE_BLOOD`, plasma class for the other four products. Step two handles the untyped patient — `current_abo_type` of `UNKNOWN` at selection time — with a hard short-circuit: a red-cell-class issue demands a group `O`, Rh `NEG` unit, and a plasma-class issue demands a group `AB` unit with Rh ignored; the matrix and restriction steps that follow are skipped entirely. Step three applies the ABO matrix for a typed patient. For an `RBC` unit: a group O-negative patient may receive only O-negative units; an O-positive patient O-negative or O-positive; an A-negative patient O-negative or A-negative; an A-positive patient O-negative, O-positive, A-negative, or A-positive; a B-negative patient O-negative or B-negative; a B-positive patient O-negative, O-positive, B-negative, or B-positive; an AB-negative patient O-negative, A-negative, B-negative, or AB-negative; and an AB-positive patient any unit. A `WHOLE_BLOOD` unit is stricter still — its ABO group and Rh type must both be identical to the patient's. Plasma-class products run in the opposite direction, donor antibodies against patient cells, with Rh ignored: a group O patient may receive plasma-class units of any group — O, A, B, or AB; an A patient only A or AB; a B patient only B or AB; and an AB patient only AB. Step four applies the order's `type_restriction`: `O_ONLY` requires the unit's group to be `O`, and `AB_ONLY` requires it to be `AB`. Step five relaxes Rh for emergencies only: for a typed patient receiving red-cell-class products, an Rh-`POS` unit may be matched to an Rh-`NEG` patient only when the order's `urgency` is `EMERGENCY` — the system's standing emergency Rh-mismatch allowance is in force — and never otherwise. Step six checks antibody coverage: every antibody named in the patient's `identified_antibodies` must appear in the unit's `antigen_negative` panel, meaning the unit tested negative for that antigen. Step seven checks special handling: an `IRRADIATED` requirement demands `irradiated` true on the unit, `CMV_NEGATIVE` demands `cmv_negative`, and `WASHED` demands `washed`. Any failed step renders the pair incompatible: an explicit selection is rejected with `ERR_UNIT_INCOMPATIBLE` (HTTP 422), while auto-selection simply excludes the unit from the candidate pool.

The **FEFO unit selector** — first-expired, first-out — builds its candidate pool from every unit in `AVAILABLE` status whose `expires_at` lies strictly beyond the current time plus the bucket's `min_shelf_life_hours` (four hours by default when the bucket has no `ACTIVE` policy) and that passes the full compatibility decision for the patient and order context. It ranks candidates by `expires_at` ascending, breaks ties by `created_at` ascending, then by `unit_number` ascending, and takes the first — a deterministic single winner with no random inputs, never consulting the record's `id`. An empty pool means `ERR_NO_COMPATIBLE_UNIT` at crossmatch or issue creation; at protocol pack dispatch it means a recorded shortfall instead of a failure (§3.6).

Recording a result drives the crossmatch out of `PENDING` — any other from-state draws `ERR_XM_NOT_PENDING`. A `result` of `COMPATIBLE` is the demanding branch: the unit must currently be `AVAILABLE` (`ERR_UNIT_NOT_AVAILABLE`, HTTP 409 — note that a unit past its `expires_at` must be swept first, and likewise yields `ERR_UNIT_NOT_AVAILABLE` while unswept), and the patient must hold an `ACTIVE` type-and-screen (`ERR_TS_NOT_ACTIVE`). On success the unit moves from `AVAILABLE` to `RESERVED` (decrementing the bucket's usable count and recomputing posture), `resulted_at` and `resulted_by_user_id` are stamped, and the reservation window is set: `reserved_until` is the earliest of seventy-two hours after `resulted_at`, the unit's `expires_at`, and the type-and-screen's `expires_at`. The window is half-open — the reservation expires the moment the current time reaches `reserved_until`, so a unit freed exactly at that instant is eligible again. The order's `units_crossmatched` increments by one, and if fulfillment thereby reaches `units_requested` the order advances from `AWAITING_CROSSMATCH` to `READY`. A `result` of `INCOMPATIBLE` is terminal and gentle: the unit was never reserved and the order's counters do not move.

Cancellation — whether invoked directly by a technologist or arriving as a cascade from an order cancel, a recall or supplier hold, or a T&S expiry — is legal from `PENDING` or `COMPATIBLE` and draws `ERR_XM_NOT_CANCELLABLE` elsewhere. From `PENDING` nothing was reserved and nothing moves. From `COMPATIBLE`, the reserved unit returns from `RESERVED` to `AVAILABLE` — except when the same cascade is moving that unit into `QUARANTINED_HOLD`, in which case the hold wins and no release occurs — while the order's `units_crossmatched` decrements by one; if fulfillment falls below `units_requested`, a `READY` order reverts to `AWAITING_CROSSMATCH`, and a `PARTIALLY_ISSUED` order reverts likewise when its `units_issued_net` has also dropped. The sweep expires a `COMPATIBLE` crossmatch whose `reserved_until` has been reached — moving it to `EXPIRED`, releasing its unit to `AVAILABLE`, decrementing `units_crossmatched`, and reverting a newly short `READY` order to `AWAITING_CROSSMATCH`. Finally, when the reserved unit is actually issued against the order, the crossmatch moves from `COMPATIBLE` to `CONSUMED` as the unit advances from `RESERVED` to `ISSUED`; `units_crossmatched` is deliberately not decremented, because the slot is now filled by the issued unit. `INCOMPATIBLE`, `EXPIRED`, `CANCELLED`, and `CONSUMED` are the terminal states.

### 3.5. Issuing Units, Transfusion, and the Thirty-Minute Return Rule

An **IssueRecord** is the custody transfer: a unit leaves the bank bound for a patient. A `BloodBankTechnologist` creates one with an `order_id` and a `verified_by_user_id` naming a second technologist who performs an independent verification — that identifier must differ from the caller's `X-User-ID`, the segregation rule on issuing, else `ERR_SEGREGATION_OF_DUTIES`. For a standard red-cell-class issue, `unit_id` is required and must name a unit `RESERVED` for this very order through a `COMPATIBLE` crossmatch; for plasma-class products and for emergency issues, `unit_id` may be omitted and the FEFO selector chooses, an empty pool surfacing `ERR_NO_COMPATIBLE_UNIT`. An explicit `unit_id` always re-runs the compatibility decision, failing with `ERR_UNIT_INCOMPATIBLE` on any failed step. The order must be `READY` or `PARTIALLY_ISSUED` — or `AWAITING_CROSSMATCH` when the issue is an emergency release — else `ERR_ORDER_NOT_ISSUABLE` (HTTP 409); and the issue quota forbids creating an issue once `units_issued_net` already equals `units_requested` (`ERR_ORDER_ISSUE_QUOTA_MET`).

Two safety rules stand in front of the red-cell supply. The **two-specimen rule** forbids issuing a red-cell-class unit whose ABO group is anything other than `O` to a patient whose `abo_confirmed` latch is still false — unless the issue is an emergency release — under `ERR_SECOND_SPECIMEN_REQUIRED` (HTTP 409). The **emergency-release rule** admits the `is_emergency_release` flag only when the order's `urgency` is `EMERGENCY` or the patient has an `ACTIVATED` massive transfusion protocol, else `ERR_EMERGENCY_RELEASE_NOT_ALLOWED` (HTTP 409); and every emergency release demands an `emergency_justification` of at least twenty characters, else `ERR_EMERGENCY_JUSTIFICATION_REQUIRED` (HTTP 422).

A created issue stamps `issued_by_user_id` and `issued_at`, denormalizes `patient_id` from the order, and records its provenance: `is_emergency_release` is computed true for a flagged issue on a qualifying order and for every protocol-dispatched unit; `mtp_activation_id` links the issue to its activation when dispatch-created and stays null otherwise. The unit moves to `ISSUED` — from `RESERVED`, consuming the crossmatch to `CONSUMED`, or directly from `AVAILABLE` for non-crossmatched and emergency flows — `units_issued_net` increments, and the order's state advances per §3.3, the first issue carrying `READY` to `PARTIALLY_ISSUED`. Creation answers 201. The issue list endpoint filters by `order_id`, `unit_id`, `patient_id`, `mtp_activation_id`, and `status`.

Bedside, the transfusion has its own clock. Starting a transfusion requires the issue to be in `ISSUED` (`ERR_ISSUE_NOT_STARTABLE`) and the current time to be no later than four hours after `issued_at` — exactly four hours is allowed, anything later is rejected with `ERR_TRANSFUSION_START_WINDOW_LAPSED` (HTTP 409). Starting stamps `transfusion_started_at` and moves the issue to `TRANSFUSION_STARTED`. Completing requires `TRANSFUSION_STARTED` (`ERR_ISSUE_NOT_COMPLETABLE`), stamps `completed_at`, and settles the issue in `TRANSFUSED`; the unit moves from `ISSUED` to `TRANSFUSED`, the order's `units_transfused` increments (completing the order when it reaches `units_requested`), and the patient's `total_units_transfused` increments — a mutation that advances the patient's `version`.

An unstarted unit may come back; a started one may not. Returning requires `ISSUED` — a transfusion once started can never be returned, and the attempt meets `ERR_ISSUE_NOT_RETURNABLE` — and takes two condition flags, `seal_intact` and `temperature_excursion`, persisted as `return_seal_intact` and `return_temperature_excursion` with `returned_at` stamped from the server clock. The **thirty-minute rule** then fixes `return_disposition`: when the return arrives at or before thirty minutes after `issued_at` with the seal intact and no temperature excursion, the disposition is `RESTOCKED` — the boundary is inclusive, so exactly thirty minutes and zero seconds restocks while thirty minutes and one second discards. A broken seal or a reported excursion, regardless of elapsed time, yields `DISCARDED_COMPROMISED`; an intact, unexcursioned return that simply arrived late yields `DISCARDED_OVER_30MIN`. A `RESTOCKED` return moves the unit from `ISSUED` back to `AVAILABLE` and recomputes posture — pointedly, the consumed crossmatch is not revived, remaining `CONSUMED`. Either discard disposition moves the unit to `DISCARDED` and writes a wastage record with reason `RETURNED_OVER_30MIN` or `RETURNED_COMPROMISED` as applicable, recomputing posture and the rolling wastage rate. Every return decrements the order's `units_issued_net` by one, which can revert the order from `PARTIALLY_ISSUED` toward `READY` or `AWAITING_CROSSMATCH` per the counter rules of §3.3.

Stopping a started transfusion short of completion — without any reaction report — requires `TRANSFUSION_STARTED` (`ERR_ISSUE_NOT_STOPPABLE`) and settles the issue in `TRANSFUSION_STOPPED`: the partially transfused unit moves to `DISCARDED` with a `PARTIAL_TRANSFUSION` wastage record, and `units_issued_net` decrements with the same order-recompute consequences. (A stop driven by a reaction report behaves differently — the unit is quarantine-held rather than discarded; §3.7 covers it.)

Emergency releases carry one obligation after the fact: the ordering physician must acknowledge the release within twenty-four hours of `issued_at`. The acknowledgement requires the issue to be an as-yet-unacknowledged emergency release (`ERR_ISSUE_NOT_ACKNOWLEDGABLE`), requires the caller to be the very physician recorded as the order's `ordering_physician_id` (`ERR_NOT_ORDERING_PHYSICIAN`, HTTP 403), and is refused after the window with `ERR_EMERGENCY_ACK_WINDOW_LAPSED` (HTTP 409); success stamps `physician_acknowledged_at`. An issue whose `is_emergency_release` is true, whose `physician_acknowledged_at` remains null, and whose twenty-four-hour mark has passed reads `ack_overdue` as true. Separately, every issue record carries `lookback_notified`, initially false, which a recall's notification pass (§3.7) sets true as look-back letters go out.

### 3.6. The Massive Transfusion Protocol

When hemorrhage outruns the orderly workflow, an `OrderingPhysician` activates the **massive transfusion protocol** for a patient, supplying `patient_id` and an `activation_reason` of at least ten characters. A patient may host at most one `ACTIVATED` protocol at a time — a second attempt meets `ERR_MTP_ALREADY_ACTIVE` (HTTP 409). Activation opens the record in `ACTIVATED`, stamps `activated_at` and `activated_by_physician_id` from the caller, and flips the patient's `active_mtp` to true, incrementing the patient's `version`. The activation list endpoint filters by `patient_id` and `status`.

Each dispatch of the next protocol pack is a `BloodBankTechnologist` action on an `ACTIVATED` record (`ERR_MTP_NOT_ACTIVE` otherwise) taking a `verified_by_user_id` — the same independent-verification rule as any issue, so it must differ from the caller's. The pack has a fixed constitution, filled in a pinned order so that later components observe earlier decrements: four `RBC` units first, then two `FFP`, then one `PLT_APHERESIS`. For each component the server walks an ABO preference list of buckets, filling within each bucket per the FEFO selector and decrementing availability immediately, then moving on. The per-bucket fill runs the §3.4 FEFO selector with its eligibility filter intact — the full compatibility decision is applied to every candidate inside the preference walk, evaluated for the dispatch with no order type-restriction and with the standing emergency Rh-mismatch allowance in force — so a preference bucket whose units all fail compatibility for the patient simply yields no candidates, and the walk moves on. For the red-cell component of a typed patient the preference runs: the patient's own group and Rh first; then O-negative; then the patient's own group with the opposite Rh; then O-positive — the latter two permitted only under the standing emergency Rh-mismatch allowance; for an untyped patient it collapses to O-negative alone. For the FFP component of a typed patient the preference runs the patient's own group with Rh-negative, then AB-negative, then A-negative, then B-negative, then O-negative, filtered to buckets plasma-compatible with the patient (an O patient keeps all four groups; an AB patient is reduced to AB-negative); for an untyped patient it is AB-negative alone. For the apheresis platelet the preference runs the patient's own group — or O when untyped — with Rh-negative, then A-negative, B-negative, AB-negative, and O-negative, de-duplicated so each bucket appears only at its first occurrence. The compatibility filter still governs inside this walk, so for an untyped patient §3.4's plasma-class short-circuit admits only group-`AB` units: the O-, A-, and B-negative buckets are walked but can fill nothing, and the platelet component is filled from AB-negative stock alone or else shortfalls. When every bucket is exhausted with a component still short, the dispatch records a shortfall naming the `product_type` and `missing_qty` and continues — dispatch never fails on short stock.

Each selected unit becomes an issue record created under emergency semantics: `is_emergency_release` true, `mtp_activation_id` set to the activation, `emergency_justification` copied from the activation's `activation_reason`, and the caller-supplied `verified_by_user_id` recorded. The dispatch answers with the `pack_number`, the created `issue_record_ids`, and the `shortfalls` array, while the activation's `packs_dispatched` increments by one and `units_issued_total` tracks every issue record created under it. Units leave `AVAILABLE` for `ISSUED` through the usual machinery.

Wind-down is two-step. Standing down — a physician action requiring `ACTIVATED` (`ERR_MTP_NOT_ACTIVE`) — moves the record to `STANDING_DOWN`, stamps `stood_down_at`, and ends the patient's emergency-release privilege immediately. Deactivation requires `STANDING_DOWN` (`ERR_MTP_NOT_STANDING_DOWN`) and is blocked while any issue record created under the activation still stands in `ISSUED` or `TRANSFUSION_STARTED` (`ERR_MTP_UNITS_OUTSTANDING`, HTTP 409) — outstanding units must be returned, completed, or stopped first. Deactivation stamps `deactivated_at`, settles the record in terminal `DEACTIVATED`, clears the patient's `active_mtp` to false (again advancing the patient's `version`), and computes `units_wasted_total` from the wastage records that reference units issued under the activation.

### 3.7. Transfusion Reactions, Investigation, and Recall

A suspected reaction is reported by a `BloodBankTechnologist` against an `issue_record_id` whose issue stands in `TRANSFUSION_STARTED` or `TRANSFUSED` — any other status draws `ERR_ISSUE_NOT_REACTIONABLE` (HTTP 409). The report names the `reaction_type` — one of `FEBRILE_NON_HEMOLYTIC`, `ALLERGIC_MILD`, `ALLERGIC_ANAPHYLAXIS`, `HEMOLYTIC_ACUTE`, `HEMOLYTIC_DELAYED`, `TRALI`, `TACO`, `SEPTIC`, or `OTHER` — and a `severity` of `MILD`, `MODERATE`, `SEVERE`, or `LIFE_THREATENING`, with optional free-text `symptoms`. The record opens in `REPORTED`, denormalizes `patient_id` and `unit_id` from the issue, and stamps `reported_by_user_id`. If the issue was mid-transfusion, reporting also stops it: the issue moves from `TRANSFUSION_STARTED` to `TRANSFUSION_STOPPED` and its unit moves from `ISSUED` to `QUARANTINED_HOLD` with `hold_reason` of `REACTION_PRECAUTION` and `hold_origin_state` of `ISSUED` — no wastage record is written yet, because the investigation may yet dispose of the unit. The reaction list endpoint filters by `issue_record_id`, `patient_id`, `unit_id`, `status`, `reaction_type`, and `linked_recall_case_id`.

Investigation belongs to the `QualityOfficer`. Beginning it requires `REPORTED` (`ERR_REACTION_NOT_INVESTIGABLE`) and an investigator whose `X-User-ID` differs from `reported_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); the officer is stamped as `investigator_user_id` and the record moves to `INVESTIGATING`. Workup entry is repeatable within `INVESTIGATING` (elsewhere `ERR_REACTION_NOT_INVESTIGATING`) and records the serologic workup: `clerical_check_passed`, the direct antiglobulin test `dat_result` (`POSITIVE` or `NEGATIVE`), and `hemolysis_present`, stamping `workup_recorded_at` on the first entry. Concluding likewise requires `INVESTIGATING` and additionally demands a recorded workup — concluding with `workup_recorded_at` still null meets `ERR_REACTION_WORKUP_MISSING` (HTTP 409). The conclusion takes `conclusion` of `CONFIRMED` or `RULED_OUT` with optional `final_classification` text.

Either conclusion disposes of a held unit the same way: if the implicated unit sits in `QUARANTINED_HOLD` under `REACTION_PRECAUTION`, it moves to `DISCARDED` with a wastage record of reason `REACTION_INVESTIGATION` — a unit involved in a reported reaction is never restocked. What differs is the blast radius of a confirmed severe reaction: concluding `CONFIRMED` with a `reaction_type` of `HEMOLYTIC_ACUTE`, `TRALI`, or `SEPTIC` auto-creates a recall case scoped `DONOR` on the unit's `donor_id` with disposition `DESTRUCTION` and `auto_created` true, runs unit identification immediately so the case is born in `UNITS_IDENTIFIED` status, and links it back through the reaction's `linked_recall_case_id`. A `RULED_OUT` conclusion creates no recall. Closing the reaction requires `CONFIRMED` or `RULED_OUT` (`ERR_REACTION_NOT_CLOSABLE`), and when `linked_recall_case_id` is set the linked recall must already stand in `NOTIFICATION_COMPLETE` or `CLOSED` — otherwise `ERR_RECALL_INCOMPLETE` (HTTP 409) holds the reaction open. `CLOSED` is terminal.

The **RecallCase** is the look-back instrument, opened by a `QualityOfficer` with a `scope_type` of `DONOR`, `LOT`, or `UNIT`, a free-text `reason`, and a `disposition` of `DESTRUCTION` or `MARKET_WITHDRAWAL` that will be applied to held units at close. Scope fields must agree with the scope type — `DONOR` requires a `donor_id`, `LOT` requires a `lot_number`, `UNIT` requires a `unit_id`, and `implicated_since` is meaningful only for `DONOR` scope — with inconsistencies rejected as `ERR_RECALL_SCOPE_INVALID` (HTTP 400). Manually opened cases carry `auto_created` false and begin in `OPEN`. The recall list endpoint filters by `status`, `scope_type`, and `unit_id`.

Identification — legal only from `OPEN` (`ERR_RECALL_NOT_IDENTIFIABLE`) — pins the implicated set into `implicated_unit_ids`: for `DONOR` scope, every unit whose `donor_id` matches, narrowed to those with `collected_at` at or after `implicated_since` when that cutoff is supplied; for `LOT` scope, every unit whose `lot_number` matches; for `UNIT` scope, the named unit plus the transitive closure of its `derived_from_unit_id` descendants — splits and aliquots of splits, however deep. The set is sorted by unit `created_at` ascending, ties broken by `unit_number` ascending, and the record's `implicated_unit_count` is its length while `transfused_issue_count` counts the notification workload — issue records in `TRANSFUSED` or `TRANSFUSION_STOPPED` that reference implicated units. The case advances to `UNITS_IDENTIFIED`.

Executing quarantine — from `UNITS_IDENTIFIED` only (`ERR_RECALL_NOT_QUARANTINABLE`) — moves every implicated unit in `QUARANTINED`, `AVAILABLE`, or `RESERVED` to `QUARANTINED_HOLD` with `hold_reason` of `RECALL` and its prior state in `hold_origin_state`; each `RESERVED` unit's `COMPATIBLE` crossmatch is cancelled and its order recomputed (a `READY` order whose fulfillment drops below `units_requested` reverts to `AWAITING_CROSSMATCH`). Units already `ISSUED`, `TRANSFUSED`, or terminal are untouched — the recall reaches them through notification instead. The tally lands in `quarantined_count` and the case moves to `QUARANTINE_COMPLETE`.

Look-back notification proceeds one issue at a time from `QUARANTINE_COMPLETE` (`ERR_RECALL_NOTIFICATIONS_NOT_COMPLETABLE` from any other state): recording a notification takes an `issue_record_id` that must reference an implicated unit and stand in `TRANSFUSED` or `TRANSFUSION_STOPPED` (`ERR_ISSUE_NOT_IMPLICATED`) and must not already be flagged (`ERR_ISSUE_ALREADY_NOTIFIED`); it sets the issue's `lookback_notified` true, increments `notifications_sent_count`, and leaves the case in `QUARANTINE_COMPLETE`. When every implicated transfused issue has been notified, completing notifications advances the case to `NOTIFICATION_COMPLETE`; attempting it with any outstanding meets `ERR_NOTIFICATIONS_PENDING` (HTTP 409). Closing — from `NOTIFICATION_COMPLETE` only, else `ERR_RECALL_NOT_CLOSABLE` — applies the disposition: under `DESTRUCTION`, each held unit (those still in `QUARANTINED_HOLD` with `hold_reason` of `RECALL`) moves to `DISCARDED` with its own wastage record of reason `RECALL_DESTRUCTION`; under `MARKET_WITHDRAWAL`, held units move to `RETURNED_TO_SUPPLIER` with no wastage record, since the units go back rather than into the bin. Either way the case settles in `CLOSED`. A false-alarm case may instead be voided from `OPEN` or `UNITS_IDENTIFIED` — crucially, before quarantine has executed — settling in `VOIDED`; from any later state the attempt draws `ERR_RECALL_NOT_VOIDABLE`.

### 3.8. Par-Level Policies, Posture Surveillance, and Wastage Tracking

Each demand bucket's standing is governed by a **ParLevelPolicy**, created by a `BloodBankSupervisor` with the bucket key — `product_type`, `abo_type`, `rh_type` — and three thresholds: `watch_threshold`, `shortage_threshold`, and `critical_threshold`, each at least zero and satisfying the ordering that `watch_threshold` must be at least `shortage_threshold`, which must be at least `critical_threshold` — violations rejected as `ERR_THRESHOLD_ORDER_INVALID` (HTTP 400). An optional `min_shelf_life_hours` (default 4) sets the usable-unit horizon: a unit counts toward the bucket only while its `expires_at` lies strictly beyond now plus that many hours. At most one `ACTIVE` policy may exist per bucket — a duplicate meets `ERR_POLICY_BUCKET_DUPLICATE` (HTTP 409) — and the policy's posture is computed immediately at creation. The policy list endpoint filters by `product_type` and `status`.

Thresholds evolve through the policy update endpoint, which requires `expected_policy_version` per §2.8 — a value that no longer matches the policy's current `version` draws `ERR_STALE_VERSION` (HTTP 412) — and accepts optional new `watch_threshold`, `shortage_threshold`, `critical_threshold`, and `min_shelf_life_hours` values, re-checking the threshold ordering (`ERR_THRESHOLD_ORDER_INVALID`), incrementing the policy's `version` by one, and recomputing posture. Update and retirement both require the policy to be `ACTIVE` (`ERR_POLICY_NOT_ACTIVE`). Retiring moves the policy to terminal `RETIRED`; while no `ACTIVE` policy exists for a bucket, the bucket is ungated and treated as `NORMAL` everywhere.

The posture read for a bucket returns its `product_type`, `abo_type`, and `rh_type`, the current `usable_units` count, the `inbound_units_24h` count (undelivered line remainders due within the next day on `SUBMITTED`, `ACKNOWLEDGED`, or `RECEIVING` orders), the `physical_posture` and `prospective_posture` per the ladders of §2.10, and the `excessive_wastage` flag. The policy resource itself mirrors the physical posture in `current_posture`, alongside `usable_units`, `inbound_units_24h`, and `excessive_wastage`, recomputed on every inventory mutation, sweep, and policy change.

Every wasted unit leaves a **WastageRecord** — the append-only log of §2.5 — carrying the `unit_id`, the unit's `product_type`, `abo_type`, and `rh_type` denormalized at write time, a `reason` of `EXPIRED`, `RETURNED_OVER_30MIN`, `RETURNED_COMPROMISED`, `PARTIAL_TRANSFUSION`, `REACTION_INVESTIGATION`, `RECALL_DESTRUCTION`, or `MANUAL`, a `quantity_units` that is always 1 in this benchmark (one record per wasted unit), the `recorded_by_user_id` of the actor whose action created it — or the literal string `system` for sweep- and closure-created records — and an optional `note` (used by manual discards). The wastage list endpoint filters by `unit_id`, `product_type`, and `reason`.

The **rolling wastage rate** grades each bucket over a thirty-day window on wastage-record `created_at`, both ends inclusive: the numerator is the sum of `quantity_units` across the bucket's records in the window, the denominator is the count of the bucket's blood units created in the window, and the rate is their quotient rounded half-up to four decimal places — or exactly 0.0000 when nothing was received. A bucket whose rate reaches or exceeds 0.05 — the boundary is inclusive — is flagged `excessive_wastage`, and that flag feeds the submission gate of §3.2: a `SupplierCoordinator` submitting a non-emergency order that touches such a bucket is stopped with `ERR_WASTAGE_REVIEW_REQUIRED`. A computed wastage summary endpoint reports `as_of_utc`, the `window_days` in effect (an optional query parameter overriding the default thirty days), and a `buckets` array of per-bucket rates, optionally narrowed by `product_type`.

### 3.9. Transport Coolers and Checkout Windows

Validated transport coolers move blood between the bank and the wards. A `BloodBankSupervisor` registers a **TransportCooler** with a unique `cooler_tag`; it opens in `AVAILABLE` with `restock_until` null, and the cooler list filters by `status`. A `BloodBankTechnologist` books a **CoolerCheckout** naming the `cooler_id` and a planned window from `planned_start` to `planned_end`. The window must be well-formed — `planned_end` strictly after `planned_start` and the duration no more than twelve hours — or the booking is rejected with `ERR_CHECKOUT_WINDOW_INVALID` (HTTP 400). Well-formed windows are then checked for conflicts against every other checkout of the same cooler under a sixty-minute redispatch buffer: a conflict exists when the new `planned_start` falls strictly before the existing checkout's effective end — that is, its `actual_returned_at` if it has returned, otherwise its `planned_end`, plus sixty minutes — and the existing checkout's `planned_start` falls strictly before the new `planned_end` plus sixty minutes; touching boundaries, where an endpoint coincides exactly, do not conflict. A conflicting booking meets `ERR_COOLER_WINDOW_CONFLICT` (HTTP 409).

Cooler status never gates booking — the interval-conflict rule alone decides — so several non-conflicting future windows may coexist on one cooler. The checkout opens in `OPEN` with `checked_out_by_user_id` stamped from the caller. Occupancy follows the window: when a created checkout's window already covers the current time — `planned_start` at or before now, now at or before `planned_end` — the cooler moves from `AVAILABLE` to `CHECKED_OUT` immediately; otherwise the sweep moves it when an `OPEN` checkout's `planned_start` is reached. A checkout whose `planned_end` passes unreturned reads `overdue` true; the sweep then releases the cooler's occupancy back from `CHECKED_OUT` to `AVAILABLE`, while the checkout itself remains `OPEN` and overdue until physically returned. Returning a checkout requires `OPEN` (`ERR_CHECKOUT_NOT_RETURNABLE`), stamps `actual_returned_at`, settles it in terminal `RETURNED`, and moves the cooler from `CHECKED_OUT` to `RESTOCKING` with `restock_until` set sixty minutes after the return — the redispatch buffer. The sweep returns a `RESTOCKING` cooler to `AVAILABLE` once `restock_until` is reached, clearing the field. The checkout list endpoint filters by `cooler_id` and `status`.

## 4. Endpoint Definitions

Operations that create a new resource answer `201 Created` — patient, supplier, supplier order, type-and-screen, transfusion order, crossmatch, issue record, protocol activation, reaction, recall case, par-level policy, cooler, and cooler checkout creation. All other operations — reads, state-transition actions, receipts, and updates — answer `200 OK` on success. The table below is a summary only; request payloads, response shapes, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/blood-bank/_clock/set_current_utc` | Set the server's logical clock (starts at 2026-08-01T00:00:00Z) | BloodBankSupervisor |
| POST | `/blood-bank/_clock/sweep` | Run time-based maintenance and cascades at the current logical time | BloodBankSupervisor |
| POST | `/blood-bank/patients` | Register a patient blood-bank record | BloodBankTechnologist, BloodBankSupervisor |
| GET | `/blood-bank/patients` | List patients | All roles |
| GET | `/blood-bank/patients/{id}` | Get one patient | All roles |
| POST | `/blood-bank/suppliers` | Register a blood supplier | BloodBankSupervisor |
| GET | `/blood-bank/suppliers` | List suppliers | All roles |
| GET | `/blood-bank/suppliers/{id}` | Get one supplier | All roles |
| POST | `/blood-bank/suppliers/{id}/suspend` | Suspend a supplier and quarantine-hold its live units | BloodBankSupervisor |
| POST | `/blood-bank/suppliers/{id}/reinstate` | Reinstate a supplier, releasing suspension holds | BloodBankSupervisor |
| POST | `/blood-bank/supplier-orders` | Create a replenishment order (estimated cost computed at create) | SupplierCoordinator, BloodBankSupervisor |
| GET | `/blood-bank/supplier-orders` | List supplier orders | All roles |
| GET | `/blood-bank/supplier-orders/{id}` | Get one supplier order | All roles |
| POST | `/blood-bank/supplier-orders/{id}/submit` | Submit an order; emergency orders auto-acknowledge | SupplierCoordinator, BloodBankSupervisor |
| POST | `/blood-bank/supplier-orders/{id}/acknowledge` | Record supplier acknowledgement | SupplierCoordinator, BloodBankSupervisor |
| POST | `/blood-bank/supplier-orders/{id}/receive` | Receive a shipment manifest, creating quarantined units | SupplierCoordinator, BloodBankSupervisor |
| POST | `/blood-bank/supplier-orders/{id}/close` | Manually close a partially received order | SupplierCoordinator, BloodBankSupervisor |
| POST | `/blood-bank/supplier-orders/{id}/cancel` | Cancel an order before any receipt | SupplierCoordinator, BloodBankSupervisor |
| GET | `/blood-bank/blood-units` | List and filter blood units | All roles |
| GET | `/blood-bank/blood-units/{id}` | Get one blood unit | All roles |
| POST | `/blood-bank/blood-units/{id}/release-from-quarantine` | Release an intake-quarantined unit to available | BloodBankTechnologist |
| POST | `/blood-bank/blood-units/{id}/reject-intake` | Reject a unit at intake | BloodBankTechnologist |
| POST | `/blood-bank/blood-units/{id}/discard` | Manual discard of a non-issued unit | BloodBankSupervisor |
| POST | `/blood-bank/type-and-screens` | Collect a type-and-screen specimen (OCC on patient version) | BloodBankTechnologist |
| GET | `/blood-bank/type-and-screens` | List type-and-screens | All roles |
| GET | `/blood-bank/type-and-screens/{id}` | Get one type-and-screen | All roles |
| POST | `/blood-bank/type-and-screens/{id}/result` | Record ABO/Rh and antibody screen results | BloodBankTechnologist |
| POST | `/blood-bank/type-and-screens/{id}/validate` | Second-technologist validation activating the specimen | BloodBankTechnologist |
| POST | `/blood-bank/type-and-screens/{id}/reject-specimen` | Reject a collected specimen | BloodBankTechnologist |
| POST | `/blood-bank/transfusion-orders` | Create a transfusion order | OrderingPhysician |
| GET | `/blood-bank/transfusion-orders` | List transfusion orders | All roles |
| GET | `/blood-bank/transfusion-orders/{id}` | Get one transfusion order | All roles |
| POST | `/blood-bank/transfusion-orders/{id}/verify` | Verify an order (typing, scarcity, and segregation gates) | BloodBankTechnologist |
| POST | `/blood-bank/transfusion-orders/{id}/reject` | Reject an unverifiable order | BloodBankTechnologist |
| POST | `/blood-bank/transfusion-orders/{id}/cancel` | Cancel an order and release its reservations | OrderingPhysician |
| POST | `/blood-bank/transfusion-orders/{id}/reactivate` | Reactivate an on-hold order after fresh typing | BloodBankTechnologist |
| POST | `/blood-bank/crossmatches` | Create a crossmatch (optional unit, else FEFO auto-select) | BloodBankTechnologist |
| GET | `/blood-bank/crossmatches` | List crossmatches | All roles |
| GET | `/blood-bank/crossmatches/{id}` | Get one crossmatch | All roles |
| POST | `/blood-bank/crossmatches/{id}/record-result` | Record a compatible or incompatible result | BloodBankTechnologist |
| POST | `/blood-bank/crossmatches/{id}/cancel` | Cancel a pending or compatible crossmatch | BloodBankTechnologist |
| POST | `/blood-bank/issue-records` | Issue a unit against an order | BloodBankTechnologist |
| GET | `/blood-bank/issue-records` | List issue records | All roles |
| GET | `/blood-bank/issue-records/{id}` | Get one issue record | All roles |
| POST | `/blood-bank/issue-records/{id}/start-transfusion` | Start the transfusion within four hours of issue | BloodBankTechnologist |
| POST | `/blood-bank/issue-records/{id}/complete-transfusion` | Complete the transfusion | BloodBankTechnologist |
| POST | `/blood-bank/issue-records/{id}/return` | Return an unstarted unit under the thirty-minute rule | BloodBankTechnologist |
| POST | `/blood-bank/issue-records/{id}/stop-transfusion` | Stop a started transfusion without a reaction report | BloodBankTechnologist |
| POST | `/blood-bank/issue-records/{id}/acknowledge-emergency` | Ordering physician acknowledges an emergency release | OrderingPhysician |
| POST | `/blood-bank/mtp-activations` | Activate the massive transfusion protocol | OrderingPhysician |
| GET | `/blood-bank/mtp-activations` | List protocol activations | All roles |
| GET | `/blood-bank/mtp-activations/{id}` | Get one protocol activation | All roles |
| POST | `/blood-bank/mtp-activations/{id}/dispatch-pack` | Dispatch the next protocol pack (records shortfalls) | BloodBankTechnologist |
| POST | `/blood-bank/mtp-activations/{id}/stand-down` | Stand down an active protocol | OrderingPhysician |
| POST | `/blood-bank/mtp-activations/{id}/deactivate` | Deactivate after stand-down with no units outstanding | OrderingPhysician |
| POST | `/blood-bank/transfusion-reactions` | Report a transfusion reaction | BloodBankTechnologist |
| GET | `/blood-bank/transfusion-reactions` | List transfusion reactions | All roles |
| GET | `/blood-bank/transfusion-reactions/{id}` | Get one transfusion reaction | All roles |
| POST | `/blood-bank/transfusion-reactions/{id}/begin-investigation` | Assign the investigating quality officer | QualityOfficer |
| POST | `/blood-bank/transfusion-reactions/{id}/record-workup` | Record serologic workup results | QualityOfficer |
| POST | `/blood-bank/transfusion-reactions/{id}/conclude` | Conclude the investigation (severe confirmed auto-recalls) | QualityOfficer |
| POST | `/blood-bank/transfusion-reactions/{id}/close` | Close a concluded reaction | QualityOfficer |
| POST | `/blood-bank/recall-cases` | Open a recall or look-back case | QualityOfficer |
| GET | `/blood-bank/recall-cases` | List recall cases | All roles |
| GET | `/blood-bank/recall-cases/{id}` | Get one recall case | All roles |
| POST | `/blood-bank/recall-cases/{id}/identify-units` | Compute and pin the implicated unit set | QualityOfficer |
| POST | `/blood-bank/recall-cases/{id}/execute-quarantine` | Quarantine-hold implicated units, cancelling crossmatches | QualityOfficer |
| POST | `/blood-bank/recall-cases/{id}/record-notification` | Mark one implicated transfused issue as notified | QualityOfficer |
| POST | `/blood-bank/recall-cases/{id}/complete-notifications` | Advance once all implicated transfused issues are notified | QualityOfficer |
| POST | `/blood-bank/recall-cases/{id}/close` | Close the recall and apply its disposition to held units | QualityOfficer |
| POST | `/blood-bank/recall-cases/{id}/void` | Void a false-alarm recall before quarantine | QualityOfficer |
| GET | `/blood-bank/wastage-records` | List wastage records | All roles |
| GET | `/blood-bank/wastage-records/{id}` | Get one wastage record | All roles |
| GET | `/blood-bank/wastage-summary` | Computed per-bucket rolling wastage rates | All roles |
| POST | `/blood-bank/par-level-policies` | Create a bucket par-level policy | BloodBankSupervisor |
| GET | `/blood-bank/par-level-policies` | List par-level policies | All roles |
| GET | `/blood-bank/par-level-policies/{id}` | Get one par-level policy | All roles |
| PUT | `/blood-bank/par-level-policies/{id}` | Update thresholds (OCC on policy version) | BloodBankSupervisor |
| POST | `/blood-bank/par-level-policies/{id}/retire` | Retire a policy | BloodBankSupervisor |
| GET | `/blood-bank/par-level-policies/{id}/posture` | Read physical and prospective posture for the bucket | All roles |
| POST | `/blood-bank/coolers` | Register a transport cooler | BloodBankSupervisor |
| GET | `/blood-bank/coolers` | List coolers | All roles |
| GET | `/blood-bank/coolers/{id}` | Get one cooler | All roles |
| POST | `/blood-bank/cooler-checkouts` | Book a cooler checkout window | BloodBankTechnologist |
| GET | `/blood-bank/cooler-checkouts` | List cooler checkouts | All roles |
| GET | `/blood-bank/cooler-checkouts/{id}` | Get one checkout | All roles |
| POST | `/blood-bank/cooler-checkouts/{id}/return` | Return a checked-out cooler, starting the restock buffer | BloodBankTechnologist |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_SUPPLIER_NOT_FOUND` | 404 Not Found |
| `ERR_SUPPLIER_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_TS_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_CROSSMATCH_NOT_FOUND` | 404 Not Found |
| `ERR_ISSUE_NOT_FOUND` | 404 Not Found |
| `ERR_REACTION_NOT_FOUND` | 404 Not Found |
| `ERR_RECALL_NOT_FOUND` | 404 Not Found |
| `ERR_WASTAGE_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_COOLER_NOT_FOUND` | 404 Not Found |
| `ERR_CHECKOUT_NOT_FOUND` | 404 Not Found |
| `ERR_MTP_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_UNIT_NOT_RELEASABLE` | 409 Conflict |
| `ERR_UNIT_NOT_REJECTABLE` | 409 Conflict |
| `ERR_UNIT_NOT_DISCARDABLE` | 409 Conflict |
| `ERR_UNIT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_UNIT_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_NO_COMPATIBLE_UNIT` | 409 Conflict |
| `ERR_TS_NOT_COLLECTED` | 409 Conflict |
| `ERR_TS_NOT_RESULTED` | 409 Conflict |
| `ERR_TS_NOT_ACTIVE` | 409 Conflict |
| `ERR_SPECIMEN_TIME_INVALID` | 400 Bad Request |
| `ERR_DUPLICATE_SPECIMEN` | 409 Conflict |
| `ERR_ANTIBODY_DETAIL_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ORDER_NOT_VERIFIABLE` | 409 Conflict |
| `ERR_ORDER_NOT_REJECTABLE` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ORDER_NOT_REACTIVATABLE` | 409 Conflict |
| `ERR_ORDER_NOT_ISSUABLE` | 409 Conflict |
| `ERR_ORDER_FULLY_CROSSMATCHED` | 409 Conflict |
| `ERR_ORDER_ISSUE_QUOTA_MET` | 409 Conflict |
| `ERR_XM_NOT_PENDING` | 409 Conflict |
| `ERR_XM_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ISSUE_NOT_STARTABLE` | 409 Conflict |
| `ERR_ISSUE_NOT_COMPLETABLE` | 409 Conflict |
| `ERR_ISSUE_NOT_RETURNABLE` | 409 Conflict |
| `ERR_ISSUE_NOT_STOPPABLE` | 409 Conflict |
| `ERR_ISSUE_NOT_REACTIONABLE` | 409 Conflict |
| `ERR_ISSUE_NOT_ACKNOWLEDGABLE` | 409 Conflict |
| `ERR_TRANSFUSION_START_WINDOW_LAPSED` | 409 Conflict |
| `ERR_EMERGENCY_RELEASE_NOT_ALLOWED` | 409 Conflict |
| `ERR_EMERGENCY_JUSTIFICATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_EMERGENCY_ACK_WINDOW_LAPSED` | 409 Conflict |
| `ERR_NOT_ORDERING_PHYSICIAN` | 403 Forbidden |
| `ERR_SECOND_SPECIMEN_REQUIRED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_MTP_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_MTP_NOT_ACTIVE` | 409 Conflict |
| `ERR_MTP_NOT_STANDING_DOWN` | 409 Conflict |
| `ERR_MTP_UNITS_OUTSTANDING` | 409 Conflict |
| `ERR_REACTION_NOT_INVESTIGABLE` | 409 Conflict |
| `ERR_REACTION_NOT_INVESTIGATING` | 409 Conflict |
| `ERR_REACTION_WORKUP_MISSING` | 409 Conflict |
| `ERR_REACTION_NOT_CLOSABLE` | 409 Conflict |
| `ERR_RECALL_INCOMPLETE` | 409 Conflict |
| `ERR_RECALL_SCOPE_INVALID` | 400 Bad Request |
| `ERR_RECALL_NOT_IDENTIFIABLE` | 409 Conflict |
| `ERR_RECALL_NOT_QUARANTINABLE` | 409 Conflict |
| `ERR_RECALL_NOTIFICATIONS_NOT_COMPLETABLE` | 409 Conflict |
| `ERR_NOTIFICATIONS_PENDING` | 409 Conflict |
| `ERR_RECALL_NOT_CLOSABLE` | 409 Conflict |
| `ERR_RECALL_NOT_VOIDABLE` | 409 Conflict |
| `ERR_ISSUE_NOT_IMPLICATED` | 409 Conflict |
| `ERR_ISSUE_ALREADY_NOTIFIED` | 409 Conflict |
| `ERR_SUPPLIER_SUSPENDED` | 409 Conflict |
| `ERR_SO_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_SO_NOT_ACKNOWLEDGEABLE` | 409 Conflict |
| `ERR_SO_NOT_RECEIVABLE` | 409 Conflict |
| `ERR_SO_NOT_CLOSABLE` | 409 Conflict |
| `ERR_SO_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_OVER_RECEIPT` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_UNIT_NUMBER` | 409 Conflict |
| `ERR_WASTAGE_REVIEW_REQUIRED` | 409 Conflict |
| `ERR_POLICY_BUCKET_DUPLICATE` | 409 Conflict |
| `ERR_THRESHOLD_ORDER_INVALID` | 400 Bad Request |
| `ERR_POLICY_NOT_ACTIVE` | 409 Conflict |
| `ERR_BUCKET_CRITICAL_ELECTIVE_BLOCKED` | 409 Conflict |
| `ERR_BUCKET_SHORTAGE_MTP_PRIORITY` | 409 Conflict |
| `ERR_CHECKOUT_WINDOW_INVALID` | 400 Bad Request |
| `ERR_COOLER_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_CHECKOUT_NOT_RETURNABLE` | 409 Conflict |
