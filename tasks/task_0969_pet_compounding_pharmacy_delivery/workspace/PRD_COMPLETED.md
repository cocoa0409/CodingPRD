# Pet Compounding Pharmacy API — Product Requirements Document

## 1. Introduction

Veterinary patients routinely need medications that no commercial product supplies: a cat that refuses pills needs a flavored suspension, a reptile needs a strength no manufacturer makes, a dog with a chicken allergy needs a formula free of poultry-derived excipients. This document specifies the Pet Compounding Pharmacy API, a platform that manages the full lifecycle of compounded veterinary prescriptions — from script intake and veterinarian verification, through bench compounding, flavoring, and quality assurance, to payment, cold-chain shipment, and delivery at the owner's door.

The domain is regulated and audit-heavy. Controlled substances impose DEA scheduling rules, a per-lot perpetual inventory log, and strict refill prohibitions. Patient safety demands allergen and species screening on every flavored compound, segregation of duties between the compounding pharmacist and the quality reviewer, and FEFO inventory discipline so that no lot is dispensed past a safe dating horizon. Cold-chain products add a second compliance axis: conditioned coolers with mandatory reconditioning windows, temperature telemetry in transit, and automatic quarantine when an excursion breaches tolerance. Recalls cut across everything — a single activated recall must freeze lots, hold in-flight orders, quarantine shipments, pause auto-ship schedules, and notify every affected owner.

Commercially, the platform supports wellness plans whose refill credits can pay for compounds, pet insurance policies whose claims are adjudicated through a deductible-and-limit waterfall, and auto-ship schedules that fire refill orders on a cadence until refills run out or the schedule fails repeatedly. All time-dependent behavior — prescription and lot expiration, cooler reconditioning, excursion accumulation, auto-ship due dates — reads a single server-side logical clock, never the wall clock, so that every rule in this document is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes seven roles, spelled exactly as follows: `Owner`, `Veterinarian`, `Pharmacist`, `PharmacyTech`, `ComplianceOfficer`, `InsuranceAdjuster`, and `PharmacyAdmin`. A request whose `X-User-Role` header is missing or does not name one of these declared roles is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not listed among the endpoint's authorized roles is rejected with `ERR_FORBIDDEN_ROLE`.

Two roles are entity-backed. When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner` record; ownership checks on any resource that references an owner compare the resource's owner foreign key to `X-User-ID`. When `X-User-Role` is `Veterinarian`, `X-User-ID` is the `id` of the acting `Veterinarian` record, and the same comparison applies to resources that reference a veterinarian. Endpoints that declare an ownership rule — veterinary confirmation, rejection, and clarification of a prescription; an owner paying for an order; an owner appealing a claim; an owner acknowledging a recall task; enrollment suspension, resumption, and cancellation; and auto-ship pause, resume, and cancellation — reject a caller whose entity-backed `X-User-ID` does not own the targeted resource with `ERR_NOT_RESOURCE_OWNER`.

The remaining five roles — `Pharmacist`, `PharmacyTech`, `ComplianceOfficer`, `InsuranceAdjuster`, and `PharmacyAdmin` — carry opaque operator identifiers. When `X-User-Role` is one of these, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `compounding_pharmacist_id` or `qa_pharmacist_id` on a compound order, or as `recorded_by` on a controlled-substance log entry — but does not compare it to any entity's `id`. Segregation-of-duties comparisons between two pharmacists on the same order compare these opaque identifiers to each other.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. Nearly all resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every modification, and `version`, an integer that starts at 1 and increments by exactly 1 on every mutation of the resource, including system-driven mutations such as cascades, auto-transitions, and sweeps. Two resources are exceptions: a `TemperatureReading` and a `ControlledSubstanceEntry` are append-only records that carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

### 2.5. The Logical Clock

The server maintains a logical clock that governs every date- and time-sensitive rule in this document: prescription and lot expiration, cooler reconditioning windows, excursion-minute accumulation, refill timing, and auto-ship due dates all read this clock. At server startup the logical clock is exactly `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time. An admin-only test-driving capability advances the clock to a supplied instant; an admin-only auto-ship run fires due schedules; and an admin-only expiration sweep expires lots and prescriptions whose dating has passed. These capabilities are described in §3.8 and listed in §4.

### 2.6. Monetary Values and Precision

All money in the system is represented as integer cents — prices, fees, surcharges, credit values, deductibles, limits, claim amounts — never as fractional currency. Whenever a multiplication or division would produce a fractional cent, the result is rounded half up to the nearest whole cent. The rounding order is part of the contract and is pinned per calculation in §3: the provisional order estimate rounds once, after summing and multiplying; the final order price rounds each lot line before summing; the shipping fee rounds its ice-pack day count up before multiplying and applies its cap last; insurance coverage rounds only the coverage multiplication; wellness-credit math rounds the discount before the credit cap is computed.

### 2.7. Optimistic Concurrency Control

Four create endpoints guard against stale parent views through optimistic concurrency control; on these endpoints the version field is a non-optional input, and no other endpoint in the API accepts a version field:

- Creating a compound order against a prescription requires `expected_prescription_version` carrying the prescription's current `version` as the client last observed it. Because the create legitimately supersedes an existing `CREATED` or `ALLOCATED` order, a writer holding a stale prescription view is turned away: if the value does not match the prescription's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating an auto-ship schedule requires `expected_prescription_version` for the same reason — a new schedule legitimately supersedes the existing `ACTIVE` one for that prescription — and a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating an insurance claim against a policy requires `expected_policy_version`; claim creation recomputes the policy's deductible estimate reserve and bumps its version, so a stale policy view is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating a wellness enrollment requires `expected_owner_version`; a new enrollment for a pet legitimately supersedes that pet's existing enrollment, so a stale owner view is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Nested Resource Retrieval

Requests that target nested resources validate path identifiers sequentially, left to right. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first path identifier that does not correspond to an existing resource, before any later identifier or business rule is examined. The same error covers body references: any foreign key supplied in a request payload that does not identify an existing resource is rejected with `ERR_NOT_FOUND`. Requests targeting undefined paths or unsupported methods are likewise rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.9. Request Evaluation Order

Every request is evaluated against a fixed sequence of checks, and an earlier failure masks all later ones:

1. **Authentication** — the `X-User-Role` header must be present and name a declared role, otherwise `ERR_UNAUTHENTICATED`.
2. **Role authorization** — the role must appear in the endpoint's authorized set, otherwise `ERR_FORBIDDEN_ROLE`.
3. **Ownership** — on ownership-guarded endpoints the entity-backed `X-User-ID` must own the targeted resource, otherwise `ERR_NOT_RESOURCE_OWNER`.
4. **Existence** — path identifiers left to right, then body references, otherwise `ERR_NOT_FOUND`.
5. **Request shape** — required fields present and correctly typed, enum values within their declared sets, pet weight greater than zero, reservation end after start, otherwise `ERR_INVALID_REQUEST`.
6. **Stale-version guard** — on the four OCC-guarded creates, otherwise `ERR_STALE_VERSION`.
7. **State checks** — a compound order under a recall hold rejects every action except resume and cancel with `ERR_RECALL_HOLD_ACTIVE` before any other state evaluation; prescription-state gates then report an expired script distinctly (`ERR_PRESCRIPTION_EXPIRED` on order creation, `ERR_PRESCRIPTION_NOT_VERIFIED` for other unverified states on creation and allocation, and `ERR_ORDER_IN_PROGRESS` when an in-flight sibling order exists); the generic from-state check rejects transitions invoked on a resource not in a permitted source state — and any further transition on a terminal-state resource — with `ERR_INVALID_STATE`; finally enrollment and policy activity gates (`ERR_ENROLLMENT_NOT_ACTIVE`, `ERR_POLICY_NOT_ACTIVE`).
8. **Business rules** — safety rules first (allergen, species, DEA registration, controlled-refill prohibition, segregation of duties, bench capability, deceased-pet), then referential rules (enrollment-pet match, claim-amount match, active-recall screening), then constraint rules (bench overlap, cooler conditioning, cooler requirement, duplicate identifiers, inventory sufficiency, refills remaining, appeal limit, waste bounds), then temporal rules (refill timing, reading monotonicity), and finally fiscal rules (`ERR_PAYMENT_REQUIRED`, `ERR_CREDIT_LIMIT`) last of all.

### 2.10. Hierarchical Consistency and Cascades

State changes propagate across the resource graph so that no child is left in an impossible condition. Suspending or revoking a veterinarian rejects that veterinarian's still-unresolved prescriptions. Marking a pet deceased cancels every auto-ship schedule hanging off that pet's prescriptions. Activating a recall quarantines covered lots, holds in-flight orders, quarantines their shipments, and pauses auto-ship schedules. Cancelling a wellness enrollment cancels the auto-ship schedules linked to it. The expiration sweep releases reservations from expiring lots and expires overdue prescriptions. Every such cascade mutates each affected resource independently: its `updated_at` refreshes and its `version` increments by 1, so a client watching any level of the hierarchy observes the change.

## 3. Business Logic & Workflows

### 3.1. Onboarding Owners, Pets, and the Prescribing Network

A `PharmacyAdmin` registers an **Owner** with a `full_name`, a contact `email` that is unique across all owners — a duplicate email is rejected with `ERR_INVALID_REQUEST` — a `phone`, and a default `ship_to_address` used for deliveries. The owner's lifecycle `status` begins as `ACTIVE` and may later become `SUSPENDED`. An owner (or an admin on their behalf) may update the contact fields `full_name`, `phone`, and `ship_to_address`; each update refreshes `updated_at` and increments `version`.

Pets are registered under their owner — either by the `Owner` themselves or by a `PharmacyAdmin` — with a `name`, a `species` drawn from `DOG`, `CAT`, `BIRD`, `REPTILE`, or `OTHER`, a `weight_kg` that must be greater than zero because it drives the pricing tier, and an optional `allergies` array of allergen tags (such as `CHICKEN`, `FISH`, or `PEANUT`) that defaults to an empty list. A pet's `status` starts as `ALIVE`. When a pet is marked `DECEASED` — a terminal change an `Owner` or `Pharmacist` may make through the pet update operation, which also accepts `weight_kg` and `allergies` changes — the system cancels every auto-ship schedule in `ACTIVE` or `PAUSED` status on that pet's prescriptions, and the pet's `version` increments.

A `PharmacyAdmin` registers each **Veterinarian** with a `full_name`, a state `license_number` that is unique across veterinarians — a duplicate is rejected with `ERR_INVALID_REQUEST` — a two-letter `practice_state`, and an optional `dea_registration_number` — without one, the veterinarian cannot prescribe controlled schedules. A new veterinarian's `status` is `PENDING` until a `ComplianceOfficer` verifies the credentials, moving the record to `VERIFIED`. A verified veterinarian may be moved to `SUSPENDED`, and a suspended one reinstated back to `VERIFIED`; either `VERIFIED` or `SUSPENDED` may move to the terminal `REVOKED`. Each of these transitions increments the veterinarian's `version`. Suspension and revocation carry a cascade: every prescription written by that veterinarian still sitting in `RECEIVED`, `VET_VERIFICATION_PENDING`, or `CLARIFICATION_REQUESTED` is rejected outright, each rejected prescription incrementing its own `version`. Prescriptions already `VERIFIED` are untouched by the cascade.

### 3.2. Catalog, Formulas, Flavorings, and Inventory Lots

The drug catalog is administered by a `PharmacyAdmin`. Each **DrugCatalogItem** records a `drug_name`, a DEA `schedule` of `NON_CONTROLLED`, `C_II`, `C_III`, `C_IV`, or `C_V`, a `requires_cold_chain` flag, the transit temperature band `cold_chain_min_celsius` (default 2) and `cold_chain_max_celsius` (default 8), a `unit_cost_cents` catalog cost per dispensing unit that may not be negative, and a `default_beyond_use_days` dating that must be greater than zero. Catalog items live in `ACTIVE` status until discontinued, at which point `status` becomes `DISCONTINUED`; the update operation accepts a `status` of `ACTIVE` or `DISCONTINUED` and sets it as supplied, so a discontinued item may be reactivated. The catalog list supports filtering by `schedule` and `status`.

**Flavorings** are likewise admin-managed: a `name`, an `allergen_tags` array defaulting to empty, a `surcharge_cents` that may not be negative, and a `compatible_species` array naming the species enum values the flavor may serve. A flavoring's `status` is `ACTIVE` at creation; no status-transition operation is exposed for flavorings.

A `Pharmacist` or `PharmacyAdmin` defines a **Formula** on top of a catalog drug via `drug_catalog_item_id`, giving it a `name`, a `dosage_form` of `SUSPENSION`, `CAPSULE`, `CHEW`, `TOPICAL`, or `INJECTABLE`, a target `strength_mg_per_ml` greater than zero, a `beyond_use_days` override greater than zero, and a nominal `base_compounding_minutes` bench time greater than zero. A formula's `status` is `ACTIVE` at creation; no status-transition operation is exposed for formulas.

Inventory arrives as **Lots**, received by a `PharmacyTech` or `PharmacyAdmin` with the stocked `drug_catalog_item_id`, a manufacturer `lot_number` that must be unique per drug — a duplicate is rejected with `ERR_DUPLICATE_LOT_NUMBER` — a `received_qty` greater than zero, an actual `unit_cost_cents` acquisition cost that may not be negative, and an `expiration_date` after which the lot is unusable. On receipt the lot's `qty_on_hand` is set to `received_qty`, while `qty_reserved`, `qty_dispensed`, and `qty_wasted` start at zero, and the lot enters `ACTIVE` status. Receiving a lot of a controlled drug writes a `RECEIVE` entry to the controlled-substance log. A lot whose `qty_on_hand` and `qty_reserved` both reach zero automatically transitions to `EXHAUSTED`; if a later release or return restores `qty_on_hand` above zero, the lot automatically returns to `ACTIVE`.

A `ComplianceOfficer` writes off units from a lot by supplying a `qty` — which must be a positive integer, otherwise `ERR_INVALID_REQUEST` — and a `reason`: `qty_on_hand` decreases by that quantity, `qty_wasted` increases by the same, the exhausted-lot check is re-evaluated, and for a controlled lot a `WASTE` log entry is written. The write-off is rejected with `ERR_WASTE_EXCEEDS_ON_HAND` when the quantity exceeds the lot's on-hand units or would drive the lot's controlled running balance below zero.

The **controlled-substance log** is a per-lot perpetual inventory. Each `ControlledSubstanceEntry` records the `lot_id` touched, an optional `compound_order_id` for dispensing entries, an `entry_type` of `RECEIVE`, `DISPENSE`, `WASTE`, `RETURN`, or `ADJUST`, a signed `qty_delta` (positive for `RECEIVE` and `RETURN`, negative for `DISPENSE` and `WASTE`), the `recorded_by` opaque operator identifier, and the `recorded_at` logical-clock timestamp. The log is replayed per lot in `recorded_at` ascending order, ties broken by `created_at` ascending and any remaining ties resolved in creation order, starting from a genesis balance of zero; each entry's `running_balance` is the previous balance plus its `qty_delta`. Any write that would make the running balance negative is rejected. At all times the latest `running_balance` for a lot equals that lot's `qty_on_hand` plus its `qty_reserved`. The log can be listed with filters on `lot_id`, `compound_order_id`, and `entry_type`.

### 3.3. Prescription Intake and Veterinary Verification

Script intake is performed by a `PharmacyTech`. The payload names the patient (`pet_id`), the customer (`owner_id`, which must equal the pet's owner — a mismatch is rejected with `ERR_INVALID_REQUEST`), the prescriber (`veterinarian_id`), and the compound (`formula_id`), together with a `quantity` of units per fill greater than zero, a `days_supply` greater than zero that drives refill timing, a `refills_authorized` count that may not be negative, free-text `directions`, and the `written_date`. Two safety gates apply at intake, evaluated in this order: a formula built on a controlled drug requires the prescribing veterinarian to hold a `dea_registration_number`, otherwise the intake is rejected with `ERR_CONTROLLED_DEA_REQUIRED`; and a `C_II` prescription must carry zero `refills_authorized`, otherwise it is rejected with `ERR_CONTROLLED_REFILL_FORBIDDEN`.

Three fields are computed at creation and are never taken from the client. The `schedule_snapshot` copies the drug's `schedule` from the catalog item at that moment — later catalog edits do not mutate it — and `is_controlled` is derived as true whenever the formula's drug schedule is anything other than `NON_CONTROLLED`. The `expiration_date` is computed as the `written_date` plus 365 days for a `NON_CONTROLLED` drug, or plus 180 days for any controlled schedule; any client-supplied expiration value is ignored. The prescription's `refills_remaining` is initialized to `refills_authorized`, `clarification_count` starts at zero, and `status` starts at `RECEIVED`.

A `PharmacyTech` sends the script out for verification, moving it from `RECEIVED` to `VET_VERIFICATION_PENDING`; this is only possible while the prescribing veterinarian is `VERIFIED`, otherwise `ERR_INVALID_STATE`. The veterinarian — and only that veterinarian, enforced by the ownership rule on the prescription's `veterinarian_id` — then has three moves. Confirmation requires the veterinarian to still be `VERIFIED` — otherwise `ERR_INVALID_STATE` — and moves the prescription to `VERIFIED`. Rejection, accompanied by a `reason`, moves it to the terminal `REJECTED`. Requesting clarification, accompanied by a `note`, moves it to `CLARIFICATION_REQUESTED` and increments `clarification_count`; the `reason` and `note` are accepted as free text but their presence is not validated. a `PharmacyTech` may then resubmit, returning the prescription to `VET_VERIFICATION_PENDING` for another round. Every one of these transitions increments the prescription's `version`.

Two system transitions close out a verified script. When a refill creation decrements `refills_remaining` to zero, the prescription auto-transitions from `VERIFIED` to `EXHAUSTED`. And when the expiration sweep finds a `VERIFIED` prescription whose `expiration_date` falls before the current logical clock date, the prescription moves to `EXPIRED` and every `ACTIVE` or `PAUSED` auto-ship schedule on it is cancelled. As described in §3.1, a veterinarian suspension or revocation rejects any of that vet's prescriptions still in `RECEIVED`, `VET_VERIFICATION_PENDING`, or `CLARIFICATION_REQUESTED`.

### 3.4. Ordering a Compound: First Fills, Refills, and Provisional Pricing

A `Pharmacist` or `PharmacyTech` creates a **CompoundOrder** against a prescription, supplying an optional `flavoring_id`, an `is_refill` flag distinguishing refills from the first fill, and the OCC field `expected_prescription_version` (§2.7). The create is guarded by a fixed sequence of checks: the stale-version guard first (`ERR_STALE_VERSION`), then prescription state — an `EXPIRED` script is reported distinctly as `ERR_PRESCRIPTION_EXPIRED`, any other non-`VERIFIED` status as `ERR_PRESCRIPTION_NOT_VERIFIED`, and a sibling order of the same prescription sitting in `COMPOUNDING`, `FLAVORING`, `REWORK`, `QA_PENDING`, `READY_TO_DISPATCH`, or `RECALL_HOLD` as `ERR_ORDER_IN_PROGRESS`. An existing sibling in `CREATED` or `ALLOCATED` is not an error: the new order supersedes it, the earlier order is auto-cancelled — releasing any reservations it held — and the new order records it in `supersedes_order_id`.

Two patient-safety screens then apply to flavored orders. If any element of the chosen flavoring's `allergen_tags` appears in the pet's `allergies`, creation is rejected with `ERR_ALLERGEN_CONFLICT`. If the pet's `species` is not among the flavoring's `compatible_species`, creation is rejected with `ERR_SPECIES_FLAVOR_INCOMPATIBLE`. The allergen screen is evaluated before the species screen.

Refills (`is_refill` true) carry four additional gates, evaluated after the safety screens. A refill against a `C_II` prescription is forbidden outright (`ERR_CONTROLLED_REFILL_FORBIDDEN`). The pet must be `ALIVE`, otherwise `ERR_PET_DECEASED`. The prescription must still have `refills_remaining` above zero, otherwise `ERR_REFILLS_EXHAUSTED`. Finally, timing: the elapsed whole days between the most recent `DISPENSED` fill of this prescription — the most recently created sibling order in `DISPENSED` status, compared by its creation date; fills that were cancelled or are still in progress do not count — and the current logical clock date must be at least the prescription's `days_supply` multiplied by three-quarters and rounded up to a whole day; the boundary day itself is eligible, and a refill arriving earlier is rejected with `ERR_REFILL_TOO_EARLY`.

Creation stamps the order with `quantity_snapshot` copied from the prescription's `quantity`, an `owner_id` copied from the prescription, a `fill_number` of 1 for a first fill that increments with each refill, `payment_status` of `UNPAID`, and `status` of `CREATED`. For a refill, the prescription's `refills_remaining` decrements by one — reaching zero drives the prescription to `EXHAUSTED` — and the prescription's `version` increments on every successful order creation.

The order's `provisional_price_cents` is estimated at creation. The base is `quantity_snapshot` multiplied by the catalog item's `unit_cost_cents`. If a flavoring was chosen, its `surcharge_cents` is added. The sum is then multiplied by a weight-tier multiplier read from the pet's `weight_kg`: 1.00 when the pet weighs under 5 kilograms; 1.15 from 5 kilograms up to but not including 15; 1.30 from 15 up to but not including 30; and 1.50 at 30 kilograms and above — each tier's lower bound is inclusive. The multiplied result is rounded half up to whole cents, once, after summing and multiplying. Finally, when the prescription's `schedule_snapshot` is any controlled schedule, a flat controlled-handling surcharge of 1500 cents is added. The `final_price_cents` remains null until quality assurance passes.

### 3.5. Bench Work: Allocation, Compounding, Flavoring, and Quality Assurance

Allocation is performed by a `PharmacyTech` and moves the order from `CREATED` to `ALLOCATED`. The prescription must be `VERIFIED` — otherwise `ERR_PRESCRIPTION_NOT_VERIFIED` — and inventory is reserved first-expiry-first-out. Candidate lots are those stocking the formula's drug, in `ACTIVE` status, whose `expiration_date` is at least the prescription's `days_supply` days beyond the current logical clock date. Candidates are walked in `expiration_date` ascending order, ties broken by `created_at` ascending; from each lot the system reserves the lesser of the remaining need and that lot's `qty_on_hand`. If the total reservable across all candidates falls short of `quantity_snapshot`, the allocation is rejected with `ERR_INSUFFICIENT_INVENTORY` and no partial allocation persists. A successful allocation creates one `LotAllocation` row per touched lot in `RESERVED` status — the allocation lifecycle spans `RESERVED`, `CONSUMED`, `RELEASED`, and `WASTED` — each recording its `compound_order_id`, `lot_id`, and `qty_allocated` with `qty_consumed` at zero; each touched lot's `qty_reserved` rises by the allocated amount and its `qty_on_hand` falls by the same; the order's `version` increments.

Starting compounding is a `Pharmacist` action that takes a `bench_id` and a reservation window `start_at` to `end_at` — the end must be after the start, otherwise `ERR_INVALID_REQUEST`. Four preconditions apply. The bench must be `ACTIVE`, otherwise `ERR_INVALID_STATE`. For a controlled order the bench's `supports_controlled` must be true, otherwise `ERR_BENCH_NOT_CONTROLLED_CAPABLE`. The new window must not overlap any existing reservation on that bench: reservation intervals are half-open — a conflict exists when the existing reservation starts before the new one ends and the new one starts before the existing one ends, so back-to-back bookings where the new `start_at` exactly equals the existing `end_at` are permitted — and a genuine overlap is rejected with `ERR_BENCH_OVERLAP`. And no `ACTIVE` recall may touch any lot allocated to the order, otherwise `ERR_RECALL_ACTIVE_ON_LOT`. Success books a `BenchReservation` on the bench — created directly in `IN_USE` status — records the caller's opaque identifier as `compounding_pharmacist_id`, and moves the order from `ALLOCATED` to `COMPOUNDING`, incrementing its `version`.

Finishing the compounding step is restricted to the same pharmacist who started it — the caller's identifier must equal `compounding_pharmacist_id`, and a different caller is rejected with `ERR_FORBIDDEN_ROLE`. Where the order carries a `flavoring_id`, the order moves from `COMPOUNDING` to `FLAVORING`; where it does not, it moves directly from `COMPOUNDING` to `QA_PENDING`. Completing flavoring, likewise restricted to the compounding pharmacist, moves the order from `FLAVORING` to `QA_PENDING`.

Quality assurance enforces segregation of duties: both the pass and the fail decision require a reviewer whose identifier differs from `compounding_pharmacist_id`, and a self-review is rejected with `ERR_SEGREGATION_OF_DUTIES`. On a pass, the reviewer's identifier is recorded as `qa_pharmacist_id`; every `RESERVED` allocation moves to `CONSUMED` with `qty_consumed` set equal to its `qty_allocated`; each lot's `qty_reserved` decreases and `qty_dispensed` increases by the consumed amount; the bench reservation moves from `IN_USE` to `COMPLETED`; the order moves from `QA_PENDING` to `READY_TO_DISPATCH`; and the `final_price_cents` is computed.

The final price uses actual lot economics rather than catalog cost. For each `CONSUMED` allocation, processed in allocation creation order with `created_at` ascending as tie-break, a line amount is computed as the `qty_consumed` multiplied by that lot's actual `unit_cost_cents` and uplifted by a three percent waste-shrink allowance, with each line rounded half up to whole cents before the lines are summed into a lot component. The flavoring's `surcharge_cents` is added if a flavoring was chosen, the same weight-tier multiplier table as the provisional price is applied, the result is rounded half up to whole cents, and the 1500-cent controlled surcharge is added when `schedule_snapshot` is controlled. Because the final price rounds per line before summing while the provisional price rounds once after summing — and because actual lot costs may differ from catalog cost — the two figures legitimately diverge on identical fill data.

A failed review moves the order from `QA_PENDING` to `REWORK` and optionally writes off wasted material: the `waste_qty` input defaults to zero — a negative value is rejected with `ERR_INVALID_REQUEST` and a `waste_qty` exceeding the order's total reserved units is rejected with `ERR_WASTE_EXCEEDS_ON_HAND` — and any positive amount reduces the `qty_allocated` of the order's `RESERVED` allocations in allocation creation order, decreases each affected lot's `qty_reserved`, increases its `qty_wasted`, and writes a `WASTE` log entry when the drug is controlled. From `REWORK`, starting compounding again is permitted once the remaining `RESERVED` allocations cover `quantity_snapshot` minus the wasted units — a shortfall is rejected with `ERR_INSUFFICIENT_INVENTORY` — under the same bench-overlap and recall rules as the first start; the fresh reservation is created directly in `IN_USE`, `compounding_pharmacist_id` is overwritten with the new caller's identifier, and the order returns to `COMPOUNDING`.

Cancellation is available to `Pharmacist` and `PharmacyTech`. From `CREATED` the order simply moves to `CANCELLED`. From `ALLOCATED`, cancellation additionally releases every `RESERVED` allocation — each moves to `RELEASED`, and each lot's `qty_reserved` decreases and `qty_on_hand` increases by the released amount — and a `BOOKED` bench reservation, if one exists, is released. Whenever a cancelled order had `payment_status` of `PAID`, an automatic refund fires: `payment_status` moves to `REFUNDED`, and if the order was `paid_via` `WELLNESS_CREDIT` the debited enrollment credits are restored. In all cases the order's `version` increments.

### 3.6. Payment, Wellness Credits, and Insurance Claims

Payment is an `Owner` operation guarded by ownership, and the order must be `UNPAID` — paying an order that is not `UNPAID` is rejected with `ERR_INVALID_STATE`. The `payment_method` is `CARD` or `WELLNESS_CREDIT`; a successful payment moves `payment_status` from `UNPAID` to `PAID` and records the tender in `paid_via`, leaving the order's lifecycle `status` untouched — payment is an independent dimension. A `Pharmacist` may later refund a paid order — refunding an order that is not `PAID` is rejected with `ERR_INVALID_STATE` — moving `payment_status` from `PAID` to `REFUNDED`; when the tender was `WELLNESS_CREDIT`, the credits originally spent are returned to the enrollment, raising `credits_remaining` and lowering `credits_consumed` by the same amount.

Wellness plans are defined by a `PharmacyAdmin` with a `name`, a `monthly_fee_cents` that may not be negative, an `included_refill_credits` grant that may not be negative, a `credit_value_cents` redemption value that must be greater than zero, a `discount_pct` fraction that is at least zero and below one, and a `covers_controlled` flag; plans live in `ACTIVE` status until `RETIRED`, and the update operation sets `status` to the supplied `ACTIVE` or `RETIRED` value, so a retired plan may be reactivated. An `Owner` enrolls a pet by supplying `pet_id`, `plan_id`, and the OCC field `expected_owner_version` (§2.7). The new enrollment supersedes that pet's existing `ACTIVE` or `SUSPENDED` enrollment, which moves to `CANCELLED` and whose linked auto-ship schedules are cancelled exactly as on an explicit cancellation; the new enrollment's `credits_remaining` initializes to the plan's `included_refill_credits`, `credits_consumed` starts at zero, `cycle_anchor_date` is set to the logical clock's date, `status` is `ACTIVE`, and the owner's `version` increments. The owner (or an admin) may suspend an `ACTIVE` enrollment, resume a `SUSPENDED` one, or cancel either — cancellation is terminal and cancels every `ACTIVE` or `PAUSED` auto-ship schedule linked via the enrollment; the owner variants of these operations are ownership-guarded. Each transition increments the enrollment's `version`.

Paying with `WELLNESS_CREDIT` requires an `enrollment_id` — omitting it is rejected with `ERR_INVALID_REQUEST` — and passes through a fixed evaluation. The enrollment must be `ACTIVE`, otherwise `ERR_ENROLLMENT_NOT_ACTIVE`. The enrollment's pet must be the prescription's pet, otherwise `ERR_ENROLLMENT_PET_MISMATCH`. When the order's `schedule_snapshot` is controlled, the plan's `covers_controlled` must be true — a plan that does not cover controlled compounds rejects the payment with `ERR_CREDIT_LIMIT`. The math then runs in five pinned steps: the subtotal is the order's `final_price_cents` when present, otherwise its `provisional_price_cents`; the discount is the subtotal multiplied by the plan's `discount_pct`, rounded half up to whole cents; the credit cap is one half of the post-discount amount — the subtotal minus the discount — rounded half up to whole cents, so the cap keys on the amount after discounting; the credits used are the lesser of the enrollment's `credits_remaining` and the credit cap divided by `credit_value_cents` rounded down to a whole credit; and the amount due is the subtotal minus the discount minus the credits used multiplied by `credit_value_cents`. If the computation yields zero credits used or a negative amount due — including the case of an enrollment with no credits left — the payment is rejected with `ERR_CREDIT_LIMIT`. A successful credit payment debits the enrollment, reducing `credits_remaining` and raising `credits_consumed` by the credits used.

Insurance policies are registered by an `Owner` or `PharmacyAdmin` with the insured `pet_id`, an `insurer_name`, a `policy_number` that must be unique — duplicates are rejected with `ERR_POLICY_NUMBER_EXISTS` — a `deductible_cents` that may not be negative, a `coverage_pct` coinsurance fraction between zero and one inclusive, an `annual_limit_cents` payout cap greater than zero, and a `renewal_date`. The counters `deductible_met_cents` and `annual_used_cents` start at zero and `status` starts at `ACTIVE`; an `InsuranceAdjuster` may lapse a policy, moving it to the terminal `LAPSED` and incrementing its `version`.

Claims are submitted by the `Owner` against a policy — each claim thereafter carries its `policy_id` — naming the `compound_order_id`, a `claimed_amount_cents` that must equal the order's `provisional_price_cents` — a mismatch is rejected with `ERR_CLAIM_AMOUNT_MISMATCH` — and the OCC field `expected_policy_version` (§2.7). The policy must be `ACTIVE`, otherwise `ERR_POLICY_NOT_ACTIVE`. At creation the claim's `estimate_cents` is computed by running the adjudication waterfall over the provisional price against the policy's snapshot at that moment, without mutating any policy counter; claim creation also recomputes the policy's deductible estimate reserve and increments the policy's `version`. The claim starts in `SUBMITTED`, with `appeal_count` at zero and `approved_amount_cents` and `deductible_applied_cents` null until adjudication.

The waterfall itself works as follows for a given amount and policy state. The deductible applied is the lesser of the amount and the policy's remaining deductible — `deductible_cents` minus `deductible_met_cents`. The remainder after the deductible is multiplied by `coverage_pct` and rounded half up to whole cents to get the covered amount. The payout is the lesser of the covered amount and the remaining annual limit — `annual_limit_cents` minus `annual_used_cents`.

Adjudication is an `InsuranceAdjuster` decision supplied as an `outcome` of `APPROVE` or `REJECT`. Approving a `SUBMITTED` claim requires the policy to be `ACTIVE` and the order's `final_price_cents` to be present; approving an `APPEALED` claim requires the policy to be `ACTIVE`. Either approval runs the waterfall over the final price against the policy's live counters — earlier `PAID` claims consume deductible and limit first, in claim creation order — and stamps `approved_amount_cents` and `deductible_applied_cents`, moving the claim to `APPROVED`; an `APPEALED` claim whose order still lacks a `final_price_cents` runs the waterfall over the provisional price instead. Rejection from either state requires a `denial_reason` and moves the claim to `REJECTED`. The owner may appeal a rejected claim — ownership-checked against the policy's owner — as long as `appeal_count` is below two; an appeal beyond the second is rejected with `ERR_MAX_APPEALS_EXCEEDED`, and each appeal increments `appeal_count` while moving the claim to `APPEALED`. Finally, an `InsuranceAdjuster` pays an `APPROVED` claim: the policy must be `ACTIVE`, otherwise `ERR_POLICY_NOT_ACTIVE`; the claim moves to the terminal `PAID`, the policy's `annual_used_cents` rises by `approved_amount_cents` and its `deductible_met_cents` rises by `deductible_applied_cents`, and both the claim's and the policy's `version` increment.

### 3.7. Dispatch, Cold Chain, and Delivery

Once an order is `READY_TO_DISPATCH`, a `Pharmacist` creates its **Shipment**, supplying the `carrier`, a `service_level` of `STANDARD`, `EXPRESS`, or `OVERNIGHT`, a `destination_zone` of `Z1`, `Z2`, or `Z3`, and — conditionally — a `cooler_asset_id`. The guards run in a fixed order: no `ACTIVE` recall may touch any lot allocated to the order (`ERR_RECALL_ACTIVE_ON_LOT`); the cooler rules apply next — a drug whose `requires_cold_chain` is true demands a `cooler_asset_id`, while an ambient drug forbids one, either violation rejected with `ERR_COLD_CHAIN_COOLER_REQUIRED`, and a cooler that is still inside its mandatory reconditioning window is rejected with `ERR_COOLER_CONDITIONING`; and the fiscal gate comes last — the order's `payment_status` must be `PAID`, otherwise `ERR_PAYMENT_REQUIRED`.

A cooler is attachable when its `status` is `AVAILABLE`, or when it is `CONDITIONING` and the current logical clock has reached its `conditioning_available_at` — arriving exactly at that timestamp is attachable; a cooler in any other status is rejected with `ERR_COOLER_CONDITIONING`. Unlike the bench's half-open adjacency, the cooler's two-hour reconditioning gap is mandatory: attaching before the gap elapses is rejected even when the prior shipment's window has ended. Attaching moves the cooler to `ASSIGNED` and increments its `version`; a cooler returning from `CONDITIONING` clears `conditioning_available_at` as it becomes `ASSIGNED` again.

Creation initializes the shipment in `LABEL_CREATED` transit status with `excursion_minutes_accumulated` at zero and `last_reading_at` null. The drug's transit band is copied onto the shipment as `required_temp_min_celsius` and `required_temp_max_celsius`, and `cold_chain_status` starts as `COMPLIANT` when the drug requires cold chain, otherwise `NOT_REQUIRED` — an independent dimension from `transit_status`. The `shipping_fee_cents` is computed at creation: a base by service level — 500 cents for `STANDARD`, 900 for `EXPRESS`, 1500 for `OVERNIGHT` — plus a 1200-cent cold-chain surcharge when the drug requires cold chain, plus an ice-pack component computed as the zone's transit hours — 24 for `Z1`, 48 for `Z2`, 72 for `Z3` — divided by twenty-four and rounded up to a whole number of days, multiplied by 300 cents per day. The total is capped: the fee is the lesser of 3500 cents and the computed sum.

A `PharmacyTech` appends **TemperatureReadings** to a shipment, each recording its `shipment_id` alongside a `recorded_at` timestamp and a `temp_celsius` value. Readings are only accepted while `cold_chain_status` is something other than `NOT_REQUIRED` — a reading on an ambient shipment is rejected with `ERR_COLD_CHAIN_NOT_REQUIRED` — and each `recorded_at` must be at least the previous reading's `recorded_at`, with non-monotonic timestamps rejected by the same error. A reading is out of range when it falls below `required_temp_min_celsius` or rises above `required_temp_max_celsius`; readings exactly at either bound are in range. The first reading establishes the baseline and accumulates zero minutes. Each subsequent out-of-range reading adds the whole minutes between its `recorded_at` and the previous reading's `recorded_at` to `excursion_minutes_accumulated`; in-range readings stop accumulation but never reset the accumulator. Readings are evaluated in `recorded_at` ascending order, ties broken by `created_at` ascending. The shipment's `cold_chain_status` becomes `EXCURSION_BREACH` once the accumulator reaches 30 minutes — exactly 30 breaches — becomes `EXCURSION_WATCH` when any minutes have accumulated or the latest reading is out of range, and otherwise remains `COMPLIANT`. A breach moves `transit_status` to `QUARANTINED` unless the shipment is already `DELIVERED` or `RETURNED_TO_PHARMACY`. Recording a reading refreshes `last_reading_at` and increments the shipment's `version`.

Transit advances through pharmacist scans. Carrier pickup moves `LABEL_CREATED` to `PICKED_UP`; it is blocked while an `ACTIVE` recall touches the order's lots (`ERR_RECALL_ACTIVE_ON_LOT`), it requires the order's `payment_status` to be `PAID`, it also requires the order to still be `READY_TO_DISPATCH` — otherwise `ERR_INVALID_STATE` — and it dispenses the order — the compound order moves from `READY_TO_DISPATCH` to `DISPENSED`, and a `DISPENSE` log entry is written for each consumed controlled lot. Further scans move `PICKED_UP` to `IN_TRANSIT` and `IN_TRANSIT` to `OUT_FOR_DELIVERY`. Delivery moves `OUT_FOR_DELIVERY` to the terminal `DELIVERED`, but only while `cold_chain_status` is not `EXCURSION_BREACH` — a delivery attempted under a breach is rejected with `ERR_INVALID_STATE`; a shipment carrying an attached cooler sends that cooler to `CONDITIONING` with `conditioning_available_at` set two hours beyond the delivery clock time. A delivery exception may be reported — a free-text `reason` is accepted but not required — from either `IN_TRANSIT` or `OUT_FOR_DELIVERY`, moving the shipment to `DELIVERY_EXCEPTION`, and a return moves it from `DELIVERY_EXCEPTION` to the terminal `RETURNED_TO_PHARMACY`, again sending any attached cooler into its two-hour `CONDITIONING` window.

Quarantine is the third terminal outcome. A cold-chain breach or a recall activation moves a shipment from `LABEL_CREATED`, `PICKED_UP`, `IN_TRANSIT`, or `OUT_FOR_DELIVERY` to `QUARANTINED`. Quarantine carries a compensation cascade: if the order's `payment_status` is `PAID` it moves to `REFUNDED`, and when the tender was `WELLNESS_CREDIT` the enrollment's `credits_remaining` is raised and its `credits_consumed` lowered by the credits originally used; an attached cooler moves from `ASSIGNED` to `CONDITIONING` with the same two-hour window; and the shipment's `version` increments. Shipments may be listed with filters on `compound_order_id`, `cooler_asset_id`, and `transit_status`.

### 3.8. Auto-Ship, the Logical Clock, and Scheduled Sweeps

An `Owner` creates an **AutoShipSchedule** on a prescription by supplying the `prescription_id`, an `interval_days` cadence greater than zero, a `next_run_date`, an optional `enrollment_id` linking a wellness plan for credit payment, and the OCC field `expected_prescription_version` (§2.7). The new schedule supersedes any existing `ACTIVE` schedule on the same prescription, which moves to `CANCELLED`; the prescription's `version` increments. A schedule starts `ACTIVE` with `consecutive_failures` at zero and `last_fired_at` null. The owner may pause an `ACTIVE` schedule, resume a `PAUSED` one, or cancel either; resume requires the prescription to be `VERIFIED` — otherwise `ERR_PRESCRIPTION_NOT_VERIFIED` — and the pet to be `ALIVE` — a deceased pet yields `ERR_PET_DECEASED` — and resets `consecutive_failures` to zero. These owner operations are ownership-guarded. Beyond the owner's own moves, schedules are cancelled by system cascades when the pet dies, the linked enrollment is cancelled, the prescription expires, or a new schedule supersedes them, and a recall activation pauses any `ACTIVE` schedule on an affected prescription. Every transition increments the schedule's `version`.

Three admin-only capabilities drive time. The clock capability sets the logical clock to a supplied `to_iso8601` instant. The auto-ship run fires every schedule whose `next_run_date` falls on or before the current clock date while `ACTIVE`, processed in creation order: each due schedule creates a refill compound order without a flavoring under exactly the same rules as a manual refill creation — including the deceased-pet, refills-remaining, and refill-timing gates — and on success advances `next_run_date` by `interval_days`, resets `consecutive_failures`, and records `last_fired_at`; on a validation failure it instead increments `consecutive_failures`, and a schedule reaching three consecutive failures auto-pauses to `PAUSED`. The expiration sweep expires every `ACTIVE` lot whose `expiration_date` falls before the clock date — moving it to `EXPIRED`, releasing all its `RESERVED` allocations with quantity restoration to the lots, and reverting any order left under-allocated from `ALLOCATED` back to `CREATED` — and expires every `VERIFIED` prescription whose `expiration_date` has passed, with the auto-ship cancellation cascade described in §3.3.

### 3.9. Recalls, Quarantine, and Owner Notification

A `ComplianceOfficer` drafts a **Recall** with a `scope` of `LOT` or `CATALOG_ITEM`, a `reason`, and a `severity` of `CLASS_I`, `CLASS_II`, or `CLASS_III`. A `LOT`-scoped draft requires a `lot_id`; a `CATALOG_ITEM`-scoped draft requires a `drug_catalog_item_id`. The recall sits in `DRAFT` until activated.

Activation stamps `activated_at` with the logical clock, moves the recall to `ACTIVE`, and fires the full cascade. Every covered lot in `ACTIVE` status moves to `QUARANTINED` with its `recall_id` set to the recall. Every compound order holding `RESERVED` or `CONSUMED` allocations from a covered lot, while in `ALLOCATED`, `COMPOUNDING`, `FLAVORING`, `QA_PENDING`, or `READY_TO_DISPATCH`, moves to `RECALL_HOLD` and records the state it came from in `hold_origin_state`; an order held out of `COMPOUNDING` additionally releases its in-use bench reservation, which moves from `IN_USE` to `RELEASED`. Each such hold cascades further: the order's shipments in `LABEL_CREATED`, `PICKED_UP`, `IN_TRANSIT`, or `OUT_FOR_DELIVERY` move to `QUARANTINED` with the refund and cooler cascades of §3.7, and `ACTIVE` auto-ship schedules on the order's prescription move to `PAUSED`. Finally, for every `DISPENSED` compound order whose lots are covered, a **RecallTask** is created recording the `recall_id`, the `compound_order_id`, and the `owner_id` to notify, with `channel` defaulting to `EMAIL` (`PHONE` being the alternative channel) and `status` starting at `PENDING`.

While an order sits in `RECALL_HOLD` it rejects every action except resume and cancel with `ERR_RECALL_HOLD_ACTIVE` — this hold rejection takes precedence over the generic invalid-state rejection for held orders. A `Pharmacist` resumes a held order only when no `ACTIVE` recall still touches any of its allocated lots (`ERR_RECALL_ACTIVE_ON_LOT`), and the resume returns the order to exactly the state recorded in `hold_origin_state` — `ALLOCATED`, `COMPOUNDING`, `FLAVORING`, `QA_PENDING`, or `READY_TO_DISPATCH` — clearing `hold_origin_state` to null and incrementing `version`. Cancelling a held order releases its `RESERVED` allocations with lot quantity restoration and auto-refunds a paid order exactly as the `ALLOCATED`-to-`CANCELLED` path does. Separately, while any `ACTIVE` recall covers a lot, starting compounding, creating a shipment, and marking a shipment picked up are all blocked with `ERR_RECALL_ACTIVE_ON_LOT`.

Notification tasks are worked by the `ComplianceOfficer`, who marks a `PENDING` task `NOTIFIED` once contact is made, or `FAILED` — a terminal outcome — when notification cannot be delivered. The owner acknowledges a `NOTIFIED` task, moving it to the terminal `ACKNOWLEDGED`; acknowledgement is ownership-guarded against the task's `owner_id`. A recall may be completed only once every one of its tasks stands at `NOTIFIED` or `ACKNOWLEDGED`; completion moves the recall to `COMPLETED` and moves every covered `QUARANTINED` lot carrying this recall's id to the terminal `RECALLED`.

Bench and cooler housekeeping round out the operational surface. A `PharmacyAdmin` registers a **CompoundingBench** with a unique `bench_code` — a duplicate is rejected with `ERR_INVALID_REQUEST` — and a `supports_controlled` flag; the bench moves between `ACTIVE` and `MAINTENANCE`, but a bench with any `BOOKED` or `IN_USE` reservation cannot be placed into maintenance — the attempt is rejected with `ERR_INVALID_STATE`. A `PharmacyAdmin` likewise registers a **CoolerAsset** with a unique `cooler_code` — a duplicate is rejected with `ERR_INVALID_REQUEST`; a cooler in `AVAILABLE` may be retired to the terminal `RETIRED`. Bench reservations may be listed with filters on `bench_id`, `compound_order_id`, and `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state-transition actions, patches, sweeps, and ops runs — return `200 OK`. The ops-run endpoints return an empty `data` object. Request and response payloads for every endpoint are governed by the narratives in §3; the table below is an index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/owners` | Register an owner | PharmacyAdmin |
| GET | `/owners/{id}` | Fetch owner | Owner, Pharmacist, PharmacyTech, ComplianceOfficer, PharmacyAdmin |
| PATCH | `/owners/{id}` | Update owner contact fields | Owner, PharmacyAdmin |
| GET | `/owners/{id}/pets` | List an owner's pets | Owner, Pharmacist, PharmacyTech, PharmacyAdmin |
| POST | `/owners/{id}/pets` | Register a pet | Owner, PharmacyAdmin |
| GET | `/pets/{id}` | Fetch pet | Owner, Veterinarian, Pharmacist, PharmacyTech, PharmacyAdmin |
| PATCH | `/pets/{id}` | Update weight/allergies or mark deceased | Owner, Pharmacist |
| POST | `/veterinarians` | Register a veterinarian | PharmacyAdmin |
| GET | `/veterinarians/{id}` | Fetch veterinarian | Veterinarian, Pharmacist, PharmacyTech, ComplianceOfficer, PharmacyAdmin |
| POST | `/veterinarians/{id}/verify` | Verify vet credentials | ComplianceOfficer |
| POST | `/veterinarians/{id}/suspend` | Suspend vet; cascades pending prescriptions to REJECTED | ComplianceOfficer |
| POST | `/veterinarians/{id}/reinstate` | Reinstate suspended vet | ComplianceOfficer |
| POST | `/veterinarians/{id}/revoke` | Revoke vet license (terminal) | ComplianceOfficer |
| POST | `/drug-catalog-items` | Add catalog drug | PharmacyAdmin |
| GET | `/drug-catalog-items` | List catalog drugs with filters and pagination | Owner, Veterinarian, Pharmacist, PharmacyTech, ComplianceOfficer, PharmacyAdmin |
| GET | `/drug-catalog-items/{id}` | Fetch drug | Owner, Veterinarian, Pharmacist, PharmacyTech, ComplianceOfficer, PharmacyAdmin |
| PATCH | `/drug-catalog-items/{id}` | Discontinue a drug | PharmacyAdmin |
| GET | `/drug-catalog-items/{id}/formulas` | List formulas built on a drug | Veterinarian, Pharmacist, PharmacyTech, PharmacyAdmin |
| POST | `/flavorings` | Add a flavoring | PharmacyAdmin |
| GET | `/flavorings` | List flavorings | Owner, Veterinarian, Pharmacist, PharmacyTech, PharmacyAdmin |
| GET | `/flavorings/{id}` | Fetch flavoring | Owner, Veterinarian, Pharmacist, PharmacyTech, PharmacyAdmin |
| POST | `/formulas` | Define a compound formula | Pharmacist, PharmacyAdmin |
| GET | `/formulas/{id}` | Fetch formula | Veterinarian, Pharmacist, PharmacyTech, PharmacyAdmin |
| POST | `/lots` | Receive an inventory lot | PharmacyTech, PharmacyAdmin |
| GET | `/lots` | List lots filtered by drug/status/recall | Pharmacist, PharmacyTech, ComplianceOfficer, PharmacyAdmin |
| GET | `/lots/{id}` | Fetch lot | Pharmacist, PharmacyTech, ComplianceOfficer, PharmacyAdmin |
| POST | `/lots/{id}/waste` | Write off units from a lot (DEA waste) | ComplianceOfficer |
| GET | `/controlled-substance-entries` | DEA log, filterable by lot or order | Pharmacist, ComplianceOfficer, PharmacyAdmin |
| GET | `/controlled-substance-entries/{id}` | Fetch one DEA log entry | Pharmacist, ComplianceOfficer, PharmacyAdmin |
| POST | `/prescriptions` | Script intake | PharmacyTech |
| GET | `/prescriptions` | List prescriptions filtered by pet/owner/vet/formula/status | Owner, Veterinarian, Pharmacist, PharmacyTech, PharmacyAdmin |
| GET | `/prescriptions/{id}` | Fetch prescription | Owner, Veterinarian, Pharmacist, PharmacyTech, PharmacyAdmin |
| POST | `/prescriptions/{id}/submit-verification` | Send script to vet for verification | PharmacyTech |
| POST | `/prescriptions/{id}/vet-confirm` | Vet confirms script (ownership-guarded) | Veterinarian |
| POST | `/prescriptions/{id}/vet-reject` | Vet rejects script | Veterinarian |
| POST | `/prescriptions/{id}/request-clarification` | Vet requests clarification (cycle) | Veterinarian |
| POST | `/prescriptions/{id}/resubmit` | Tech resubmits after clarification | PharmacyTech |
| POST | `/prescriptions/{id}/compound-orders` | Create first-fill or refill compound order (OCC on Prescription; supersedes CREATED/ALLOCATED order) | Pharmacist, PharmacyTech |
| GET | `/prescriptions/{id}/compound-orders` | List orders of a prescription | Owner, Pharmacist, PharmacyTech, PharmacyAdmin |
| GET | `/compound-orders` | List orders filtered by owner/prescription/flavoring/supersede/status | Owner, Pharmacist, PharmacyTech, ComplianceOfficer, PharmacyAdmin |
| GET | `/compound-orders/{id}` | Fetch order | Owner, Pharmacist, PharmacyTech, ComplianceOfficer, InsuranceAdjuster, PharmacyAdmin |
| GET | `/compound-orders/{id}/allocations` | List lot allocations of an order | Pharmacist, PharmacyTech, ComplianceOfficer, PharmacyAdmin |
| GET | `/lot-allocations` | List allocations filtered by lot or order | Pharmacist, PharmacyTech, ComplianceOfficer, PharmacyAdmin |
| GET | `/lot-allocations/{id}` | Fetch one allocation | Pharmacist, PharmacyTech, ComplianceOfficer, PharmacyAdmin |
| POST | `/compound-orders/{id}/allocate` | FEFO-allocate lots | PharmacyTech |
| POST | `/compound-orders/{id}/start-compounding` | Book bench and start compounding | Pharmacist |
| POST | `/compound-orders/{id}/complete-compounding` | Finish compounding step | Pharmacist |
| POST | `/compound-orders/{id}/complete-flavoring` | Finish flavoring step | Pharmacist |
| POST | `/compound-orders/{id}/qa-pass` | QA approval by a different pharmacist | Pharmacist |
| POST | `/compound-orders/{id}/qa-fail` | QA rejection to rework | Pharmacist |
| POST | `/compound-orders/{id}/resume` | Resume from recall hold | Pharmacist |
| POST | `/compound-orders/{id}/cancel` | Cancel order with compensation | Pharmacist, PharmacyTech |
| POST | `/compound-orders/{id}/pay` | Pay by card or wellness credit | Owner |
| POST | `/compound-orders/{id}/refund` | Refund a paid order | Pharmacist |
| POST | `/compound-orders/{id}/shipments` | Create shipment for a paid ready order | Pharmacist |
| GET | `/shipments/{id}` | Fetch shipment | Owner, Pharmacist, PharmacyTech, ComplianceOfficer, PharmacyAdmin |
| GET | `/shipments` | List shipments filtered by order/cooler/transit status | Owner, Pharmacist, PharmacyTech, ComplianceOfficer, PharmacyAdmin |
| POST | `/shipments/{id}/temperature-readings` | Append a cold-chain temperature reading | PharmacyTech |
| GET | `/shipments/{id}/temperature-readings` | List readings of a shipment | Pharmacist, PharmacyTech, ComplianceOfficer, PharmacyAdmin |
| POST | `/shipments/{id}/mark-picked-up` | Carrier pickup | Pharmacist |
| POST | `/shipments/{id}/mark-in-transit` | Transit scan | Pharmacist |
| POST | `/shipments/{id}/mark-out-for-delivery` | Out-for-delivery scan | Pharmacist |
| POST | `/shipments/{id}/mark-delivered` | Delivery confirmation | Pharmacist |
| POST | `/shipments/{id}/report-exception` | Delivery exception | Pharmacist |
| POST | `/shipments/{id}/mark-returned` | Return to pharmacy | Pharmacist |
| POST | `/compounding-benches` | Register a bench | PharmacyAdmin |
| GET | `/compounding-benches/{id}` | Fetch bench | Pharmacist, PharmacyTech, PharmacyAdmin |
| PATCH | `/compounding-benches/{id}` | Set bench status | PharmacyAdmin |
| GET | `/bench-reservations` | List reservations filtered by bench or order | Pharmacist, PharmacyTech, PharmacyAdmin |
| GET | `/bench-reservations/{id}` | Fetch one reservation | Pharmacist, PharmacyTech, PharmacyAdmin |
| POST | `/cooler-assets` | Register a cooler | PharmacyAdmin |
| GET | `/cooler-assets/{id}` | Fetch cooler | Pharmacist, PharmacyTech, PharmacyAdmin |
| GET | `/cooler-assets` | List coolers | Pharmacist, PharmacyTech, PharmacyAdmin |
| PATCH | `/cooler-assets/{id}` | Retire a cooler | PharmacyAdmin |
| POST | `/wellness-plans` | Define a wellness plan | PharmacyAdmin |
| GET | `/wellness-plans` | List wellness plans | Owner, Pharmacist, PharmacyTech, PharmacyAdmin |
| GET | `/wellness-plans/{id}` | Fetch plan | Owner, Pharmacist, PharmacyTech, PharmacyAdmin |
| PATCH | `/wellness-plans/{id}` | Retire a plan | PharmacyAdmin |
| POST | `/enrollments` | Enroll a pet in a wellness plan (OCC on Owner; supersedes the pet's existing enrollment) | Owner |
| GET | `/enrollments/{id}` | Fetch enrollment | Owner, Pharmacist, PharmacyAdmin |
| GET | `/enrollments` | List enrollments filtered by owner/pet/plan/status | Owner, Pharmacist, PharmacyAdmin |
| POST | `/enrollments/{id}/suspend` | Suspend enrollment | Owner, PharmacyAdmin |
| POST | `/enrollments/{id}/resume` | Resume enrollment | Owner, PharmacyAdmin |
| POST | `/enrollments/{id}/cancel` | Cancel enrollment | Owner, PharmacyAdmin |
| POST | `/insurance-policies` | Register an insurance policy | Owner, PharmacyAdmin |
| GET | `/insurance-policies/{id}` | Fetch policy | Owner, InsuranceAdjuster, PharmacyAdmin |
| GET | `/insurance-policies` | List policies filtered by owner/pet/status | Owner, InsuranceAdjuster, PharmacyAdmin |
| POST | `/insurance-policies/{id}/lapse` | Lapse a policy | InsuranceAdjuster |
| POST | `/insurance-policies/{id}/claims` | Submit a claim (OCC on InsurancePolicy) | Owner |
| GET | `/claims/{id}` | Fetch claim | Owner, InsuranceAdjuster, PharmacyAdmin |
| GET | `/claims` | List claims filtered by policy/order/status | Owner, InsuranceAdjuster, PharmacyAdmin |
| POST | `/claims/{id}/adjudicate` | Approve or reject a claim | InsuranceAdjuster |
| POST | `/claims/{id}/appeal` | Appeal a rejected claim (max 2) | Owner |
| POST | `/claims/{id}/pay` | Pay an approved claim | InsuranceAdjuster |
| POST | `/auto-ship-schedules` | Create an auto-ship schedule (OCC on Prescription; supersedes existing ACTIVE schedule) | Owner |
| GET | `/auto-ship-schedules/{id}` | Fetch schedule | Owner, Pharmacist, PharmacyTech, PharmacyAdmin |
| GET | `/auto-ship-schedules` | List schedules filtered by prescription/enrollment/status | Owner, Pharmacist, PharmacyTech, PharmacyAdmin |
| POST | `/auto-ship-schedules/{id}/pause` | Pause schedule | Owner |
| POST | `/auto-ship-schedules/{id}/resume` | Resume schedule | Owner |
| POST | `/auto-ship-schedules/{id}/cancel` | Cancel schedule | Owner |
| POST | `/recalls` | Draft a recall | ComplianceOfficer |
| GET | `/recalls/{id}` | Fetch recall | Owner, Pharmacist, ComplianceOfficer, PharmacyAdmin |
| GET | `/recalls` | List recalls filtered by lot/drug/status | Pharmacist, ComplianceOfficer, PharmacyAdmin |
| POST | `/recalls/{id}/activate` | Activate recall; fires the quarantine/hold/notify cascade | ComplianceOfficer |
| POST | `/recalls/{id}/complete` | Complete recall once all tasks notified | ComplianceOfficer |
| GET | `/recalls/{id}/tasks` | List tasks of a recall | Owner, ComplianceOfficer, PharmacyAdmin |
| GET | `/recall-tasks` | List recall tasks filtered by recall/order/owner/status | Owner, ComplianceOfficer, PharmacyAdmin |
| GET | `/recall-tasks/{id}` | Fetch one recall task | Owner, ComplianceOfficer, PharmacyAdmin |
| POST | `/recall-tasks/{id}/mark-notified` | Mark owner notification sent | ComplianceOfficer |
| POST | `/recall-tasks/{id}/mark-failed` | Mark notification failed | ComplianceOfficer |
| POST | `/recall-tasks/{id}/acknowledge` | Owner acknowledges a recall notice | Owner |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the logical clock. Server startup default is exactly 2026-05-01T00:00:00Z and never falls back to wall-clock time. | PharmacyAdmin |
| POST | `/_ops/auto_ship_run` | Test-driving endpoint: fire due auto-ship schedules | PharmacyAdmin |
| POST | `/_ops/expiration_sweep` | Test-driving endpoint: expire lots and prescriptions whose expiration has passed | PharmacyAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is an index of identifiers to HTTP status codes only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PRESCRIPTION_NOT_VERIFIED` | 409 |
| `ERR_PRESCRIPTION_EXPIRED` | 409 |
| `ERR_ORDER_IN_PROGRESS` | 409 |
| `ERR_RECALL_HOLD_ACTIVE` | 409 |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 |
| `ERR_POLICY_NOT_ACTIVE` | 409 |
| `ERR_ALLERGEN_CONFLICT` | 422 |
| `ERR_SPECIES_FLAVOR_INCOMPATIBLE` | 422 |
| `ERR_CONTROLLED_DEA_REQUIRED` | 422 |
| `ERR_CONTROLLED_REFILL_FORBIDDEN` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_BENCH_NOT_CONTROLLED_CAPABLE` | 422 |
| `ERR_PET_DECEASED` | 422 |
| `ERR_ENROLLMENT_PET_MISMATCH` | 422 |
| `ERR_CLAIM_AMOUNT_MISMATCH` | 422 |
| `ERR_RECALL_ACTIVE_ON_LOT` | 409 |
| `ERR_BENCH_OVERLAP` | 409 |
| `ERR_COOLER_CONDITIONING` | 409 |
| `ERR_COLD_CHAIN_COOLER_REQUIRED` | 422 |
| `ERR_DUPLICATE_LOT_NUMBER` | 409 |
| `ERR_POLICY_NUMBER_EXISTS` | 409 |
| `ERR_INSUFFICIENT_INVENTORY` | 422 |
| `ERR_REFILLS_EXHAUSTED` | 422 |
| `ERR_MAX_APPEALS_EXCEEDED` | 422 |
| `ERR_WASTE_EXCEEDS_ON_HAND` | 422 |
| `ERR_REFILL_TOO_EARLY` | 422 |
| `ERR_COLD_CHAIN_NOT_REQUIRED` | 422 |
| `ERR_PAYMENT_REQUIRED` | 402 |
| `ERR_CREDIT_LIMIT` | 402 |
