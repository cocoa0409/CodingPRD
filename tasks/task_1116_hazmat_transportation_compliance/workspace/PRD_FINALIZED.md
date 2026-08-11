# Hazmat Transportation Compliance API — Product Requirements Document

## 1. Introduction

Moving hazardous materials across public roads is a heavily regulated activity in which a single paperwork error or a single incompatible pairing of packages can end in fines, impounded vehicles, or worse. The office responsible for a shipper's compliance posture must answer the same chain of questions for every consignment: is the carrier's registration in force, is the chosen packaging authorized for this hazard class and packing group, does the mixed load demand placards at an aggregate threshold, are the driver's endorsement and training records still current, has the security plan covering this category been approved for today's date, and — if something goes wrong — have the phone and written reporting deadlines been met. Today these answers live in spreadsheets, binders, and institutional memory, which makes the process fragile exactly when it matters most.

This document specifies a REST API that a hazmat shipper's compliance office uses to run that chain end-to-end. The system covers carrier registration with a tiered fee schedule and late-renewal penalties, a regulator-curated catalog of materials and authorized packaging specifications, a shipment lifecycle from classification through packaging verification, shipping-paper certification, tendering, loading, dispatch, and delivery, plus an incident-reporting workflow whose deadlines and penalties are computed rather than remembered. A logical clock — settable only by the regulator — drives all temporal rules (expiry sweeps, deadline lateness, training-renewal windows), so every determination is reproducible. All resources are mounted under the `/hazmat` prefix.

The design enforces segregation of duties deliberately: the officer who classifies a shipment may not certify its shipping paper; the carrier administrator who files registration paperwork may not approve it; and an optimistic-concurrency scheme protects the two flows (shipment amendment and registration submission) where one writer's superseding edit must not be silently overwritten by another reader's stale view.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the acting role. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is well-formed but not permitted for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Three roles exist, spelled exactly:

- `CarrierAdmin` — the carrier-side administrator responsible for registration submission, payments, security plans, drivers, and vehicles.
- `ShipperComplianceOfficer` — the shipper's compliance office: shipment classification, packaging verification, shipping-paper certification, tendering, load and placard management, and incident filing. Segregation of duties applies within this role on the certify action (see §3.4).
- `Regulator` — the regulatory authority: material and packaging catalog management, route management, registration approval, suspension and reinstatement, security-plan approval, shipment rejection, incident closure, invoice voiding, and control of the logical clock.

All three roles carry `identity: opaque`. When `X-User-Role` is `CarrierAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `Regulator`, the same holds: an opaque identifier, never compared against a resource. When `X-User-Role` is `ShipperComplianceOfficer`, `X-User-ID` is likewise an opaque operator identifier, but the server records it in two specific places because of the segregation-of-duties rule: as `classified_by_user_id` on the `Shipment` when the officer performs classification, and as `certified_by_user_id` on the `ShippingPaper` at certification; the certification step then rejects the request when the two recorded identifiers coincide.

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

List endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10, with a minimum accepted value of 1 and a maximum of 100; `offset` defaults to 0. Every list response's `meta` block carries `limit`, `offset`, `total_count`, and `has_more`. Unless an endpoint states otherwise, list results are ordered by `created_at` ascending.

Most list endpoints additionally accept equality filters drawn from the resource's own fields: the carrier list filters by `registration_status`; the invoice, security-plan, packaging-spec, driver, vehicle, shipment, load, and incident lists each filter by `status`; the material list filters by `hazard_class` and `placard_table`; the driver list also filters by `qualification_posture`; shipment lists filter by `material_id`, `packaging_spec_id`, and `driver_id`, with the global shipment list also filtering by `carrier_id`; the load list filters by `vehicle_id` and `route_id`; the route list filters by `route_code`; and the incident list filters by `shipment_id` and `carrier_id`.

### 2.4. The Logical Clock and Time-Driven Sweeps

All temporal reasoning in the system — registration expiry, plan windows, endorsement validity, training expiry, incident deadlines, dispatch route windows — is evaluated against a single logical clock, never against wall-clock time. The clock's startup value is exactly 2026-05-01T00:00:00Z, and it changes only when a `Regulator` advances it through the clock-setting capability, supplying the target instant as `to_iso8601`. Advancing the clock fires a system sweep with three effects: any carrier whose `registration_expires_at` has been passed moves from `APPROVED_ACTIVE` to `EXPIRED`; any security plan in `APPROVED` whose `effective_to` has been passed moves to `EXPIRED`; and every driver's `qualification_posture` is refreshed per the posture rule in §3.5. Datetimes elsewhere in the system are compared at one-second granularity; weights are compared at one decimal of precision; all monetary values are integer cents.

### 2.5. Common Resource Properties

Most resources carry four system-maintained fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. The same three-fractional-digit ISO 8601 UTC serialization (for example, `2026-06-01T12:00:00.000Z`) applies to every non-null datetime the server emits in a response — including computed datetimes such as `phone_deadline`, `written_report_deadline`, and a training record's `expires_at`, supplied datetimes echoed back such as `hazmat_endorsement_expires_at`, `effective_from`, `effective_to`, `planned_departure_at`, `planned_arrival_at`, and `occurred_at`, and clock-derived stamps such as `registration_expires_at`, `approved_at`, `phone_reported_at`, and `written_filed_at`. `version` is an integer that increments by 1 on every mutation of the resource and underpins optimistic concurrency. Two resource kinds are deliberately lighter: `TrainingRecord` and `LoadItem` carry only `id` and `created_at` — neither has `updated_at` nor `version`, and no OCC field is ever accepted for them.

### 2.6. Optimistic Concurrency Control

Exactly two write operations are version-guarded; no other endpoint accepts a version field. Amending a shipment requires the request to carry `expected_shipment_version`, the value of the shipment's `version` as last observed by the client; if the shipment's current `version` differs — because another writer has since amended the same shipment, a legitimate superseding edit — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Submitting a carrier's registration likewise requires `expected_carrier_version`; if the carrier's `version` has advanced since the client last read it (another writer's submission having superseded the draft under the renewal flow), the submission is rejected with `ERR_STALE_VERSION` (HTTP 412). Both rejections exist so a client never overwrites state it has not observed.

### 2.7. Monetary Values, Rounding, and Precision

All money is expressed in integer cents. Every computed monetary component — the security surcharge, the late fee, the safety discount, the processing fee, each per-item handling line — is rounded half-up to whole cents at the step where it is produced, and components are then integer-summed; summing first and rounding once at the end is a different, rejected reading. The incident penalty's confirmed variant rounds half-up at its final multiplier step. Nothing in the system accepts or returns fractional cents.

### 2.8. Request Validation Order and Existence Checks

Validation on any request proceeds in a fixed order, and the first failing check determines the error returned. Authentication headers come first (§2.1), then role authorization, then path-parameter existence — path identifiers are validated left-to-right, so on a nested path the outermost resource is checked before the inner one, and a missing resource yields its specific not-found error (`ERR_CARRIER_NOT_FOUND`, `ERR_SECURITY_PLAN_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_SHIPPING_PAPER_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, each HTTP 404). Next comes request-shape validation: required fields present, types valid, enum members valid, and numeric/date ranges valid — `quantity_kg` must be greater than 0, `fleet_size_declared` must be at least 0, `declared_value_cents` must be at least 0, a plan's or route's `effective_to` must be strictly later than its `effective_from`, a load's `planned_arrival_at` must be strictly later than its `planned_departure_at`, a payment's `amount_cents` must be greater than 0, and `shipper_certification_signed` must be a boolean; any violation yields `ERR_INVALID_REQUEST` (HTTP 400). After shape validation, body foreign-key references are resolved (`material_id`, `packaging_spec_id`, `driver_id`, `vehicle_id`, `route_id`, `shipment_id`); a reference to a nonexistent resource yields `ERR_INVALID_REFERENCE` (HTTP 422). OCC version checks follow, then the carrier-active aggregate gate, then the target resource's from-state gate, and only then the domain safety, temporal, fiscal, and uniqueness rules described in §3.

### 2.9. Uniqueness Constraints

Five identifiers are globally unique and a duplicate create is rejected: `usdot_number` with `ERR_DUPLICATE_USDOT`, `cdl_number` with `ERR_DUPLICATE_CDL`, `plate_number` with `ERR_DUPLICATE_PLATE`, `un_na_number` with `ERR_DUPLICATE_UN_NA`, and `spec_code` with `ERR_DUPLICATE_SPEC_CODE` (all HTTP 409). Two further structural uniqueness rules hold: a shipment has at most one shipping paper — a second create yields `ERR_DUPLICATE_SHIPPING_PAPER` — and a shipment may appear on at most one non-terminal load at a time, enforced as `ERR_SHIPMENT_ALREADY_LOADED` (§3.6).

## 3. Business Logic & Workflows

### 3.1. Carrier Registration: Submission, Approval, and the Fee Schedule

A carrier's life begins when a `CarrierAdmin` registers the company, supplying its `legal_name`, its `usdot_number`, the declared power-unit count `fleet_size_declared` (which must be at least 0), the set of category authorizations `hazmat_categories` drawn from `EXPLOSIVE`, `FLAMMABLE_LIQUID`, `OXIDIZER`, `RADIOACTIVE`, `INHALATION_TOXIC`, `CORROSIVE`, and `MISC`, and optionally `accepts_dangerous_placard_substitution` (defaulting to false), which records whether this carrier permits the DANGEROUS placard substitution on mixed Table-2 loads (§3.7). A new carrier starts in `DRAFT` with `safety_rating` at 100, `credit_balance_cents` at 0, and `verified_fleet_size` and `registration_expires_at` both null until the first approval.

Submitting the registration is the OCC-guarded write described in §2.6 and is available from `DRAFT`, from `EXPIRED`, and — as an early renewal — from `APPROVED_ACTIVE` when the clock lies inside the closed window that opens thirty days before `registration_expires_at` and ends at `registration_expires_at`. Outside those states or outside that window the submission is rejected with `ERR_CARRIER_NOT_SUBMITTABLE` (HTTP 409). A submission from `DRAFT` creates a `RegistrationInvoice` whose `kind` is `INITIAL`; a submission from `EXPIRED` or an early renewal creates one whose `kind` is `RENEWAL`. Either way the invoice's `assessment_year` records the calendar year of the clock at assessment, `paid_cents` starts at 0, its `status` is `OPEN`, and the carrier's `version` increments by 1 as its `registration_status` moves to `SUBMITTED`.

The provisional fee computed at submission uses `fleet_size_declared` and never applies a safety discount. The fee schedule is tiered. A fleet of at most 10 power units is `SMALL` with a base of 25000 cents; a fleet of 11 through 50 is `MEDIUM` with a base of 100000 cents; a fleet of 51 or more is `LARGE`, whose base is 250000 cents plus 2500 cents for every power unit beyond 50. The carrier's `registration_tier` records this tier as derived from the fleet input. When the carrier's `hazmat_categories` intersect `EXPLOSIVE`, `RADIOACTIVE`, or `INHALATION_TOXIC` — which is precisely the condition recorded on the carrier as `security_plan_required` — a surcharge of 50 percent of the base, rounded half-up to whole cents, is added; otherwise the surcharge is 0. For `RENEWAL` invoices only, a late fee applies: `months_late` counts the started calendar months strictly after `registration_expires_at` up to the clock — 0 while the clock is at or before the expiry instant, 1 when the clock lies after expiry and within one month past it, and one more for each further started month — and the late percentage is the lesser of 10 percent per month late and a 50 percent cap, applied to the sum of base and surcharge and rounded half-up. (An early renewal inside the pre-expiry window therefore always computes `months_late` as 0.) The subtotal is base plus surcharge plus late fee minus discount — the discount being 0 in the provisional variant. A processing fee follows: when the subtotal, evaluated before the fee is added, is at least 100000 cents, the fee is 3 percent of that subtotal rounded half-up; otherwise it is a flat 2500 cents. The invoice's `provisional_total_cents` is the resulting total, and `total_due_cents` mirrors the provisional figure until approval.

Approval belongs to the `Regulator` and requires the carrier to be `SUBMITTED`, else `ERR_CARRIER_NOT_SUBMITTED` (HTTP 409). The approving payload carries `verified_fleet_size`, which is stored on the carrier verbatim, and the open `INITIAL` or `RENEWAL` invoice is recomputed at the final variant: the same tiered schedule, but with `verified_fleet_size` as the fleet input and with a safety discount now applied — 5 percent of the base when the carrier's `safety_rating` is at least 95, 2.5 percent when the rating is at least 90 but below 95, and nothing below 90, the discount itself rounded half-up. The recomputed figure replaces the provisional one: `final_total_cents` is set, and `total_due_cents` switches from the provisional amount to the final amount. Approval also sets `registration_expires_at` to one year after the clock instant and moves the carrier to `APPROVED_ACTIVE`.

Suspension is a `Regulator` action requiring `APPROVED_ACTIVE`, else `ERR_CARRIER_NOT_ACTIVE`. It triggers a three-level cascade, spelled out in §3.6 because its effects land on drivers, shipments, and loads. Reinstatement requires `SUSPENDED`, else `ERR_CARRIER_NOT_SUSPENDED`, creates an invoice whose `kind` is `REINSTATEMENT` with a flat `total_due_cents` of 75000 cents — no tiered calculation, no processing fee, no discount; for such invoices `provisional_total_cents` is null and `final_total_cents` equals the flat amount — and returns every `SUSPENDED` driver of the carrier to `ACTIVE`. There is no operator-driven expiry: only the clock sweep (§2.4) moves a carrier from `APPROVED_ACTIVE` to `EXPIRED`.

### 3.2. Payments, Credits, and the Outstanding Balance

A carrier's open receivables are tracked on `RegistrationInvoice` records, and the carrier's `outstanding_balance_cents` is always the sum, over exactly its `OPEN` invoices, of each invoice's `total_due_cents` minus its `paid_cents`; `PAID` and `VOID` invoices contribute nothing. A `CarrierAdmin` applies funds through the carrier's payment capability by supplying `amount_cents`. The allocation is a waterfall. The pool begins as the payment amount plus the carrier's `credit_balance_cents`, so previously overpaid credit is consumed first. The targets are the carrier's `OPEN` invoices ordered by `assessment_year` ascending, ties broken by `created_at` ascending — never by id. Each invoice in turn receives the lesser of its remaining due and the remaining pool; an invoice whose `paid_cents` reaches its `total_due_cents` flips from `OPEN` to `PAID`. Any pool remainder after all open invoices are satisfied is held as the carrier's new `credit_balance_cents`, and the carrier's `outstanding_balance_cents` is recomputed.

Consider a carrier with two open invoices, the older due 30000 cents and the newer due 50000 cents, and a payment of 45000 cents with no stored credit: the older invoice absorbs 30000 and becomes `PAID`, the newer absorbs 15000 and stays `OPEN`, and the outstanding balance lands at 35000 cents. A `Regulator` may also void an `OPEN` invoice as a compensating action — any other status yields `ERR_INVOICE_NOT_VOIDABLE` — which moves the invoice to `VOID` and recomputes the balance with the voided invoice excluded.

### 3.3. Catalogs: Materials, Packaging Specifications, and Retirements

The `Regulator` maintains the hazardous-materials catalog. Each material records its `un_na_number` (unique), its regulatory `proper_shipping_name`, a `hazard_class` drawn from `CLASS_1_1`, `CLASS_1_2`, `CLASS_1_3`, `CLASS_2_1`, `CLASS_2_2`, `CLASS_2_3`, `CLASS_3`, `CLASS_4_1`, `CLASS_4_2`, `CLASS_4_3`, `CLASS_5_1`, `CLASS_5_2`, `CLASS_6_1`, `CLASS_6_2`, `CLASS_7`, `CLASS_8`, and `CLASS_9`, a `packing_group` of `PG_I`, `PG_II`, `PG_III`, or `PG_NONE`, a `placard_table` of `TABLE_1` or `TABLE_2`, a `transport_category` from the same category enumeration carriers are authorized for, its CERCLA `reportable_quantity_lbs`, an optional `is_inhalation_hazard` flag (default false), an optional `segregation_group` of `SG_NONE`, `SG_ACID`, `SG_ALKALI`, `SG_OXIDIZER`, or `SG_FLAMMABLE` (default `SG_NONE`), and the `erg_guide_number` that shipping papers will copy. A material is computed to `requires_security_plan` when any of three conditions holds: its `placard_table` is `TABLE_1`, or `is_inhalation_hazard` is true, or its `hazard_class` is `CLASS_7`.

The packaging catalog, also regulator-maintained, records each specification's unique `spec_code`, the `authorized_hazard_classes` it may contain, its `max_packing_group`, and its `max_net_quantity_kg`. A new spec starts `ACTIVE`. Packing-group compatibility is directional: `PG_I` packaging accepts `PG_I`, `PG_II`, and `PG_III` material; `PG_II` packaging accepts `PG_II` and `PG_III`; `PG_III` packaging accepts only `PG_III`. A material whose `packing_group` is `PG_NONE` is compatible with any specification's `max_packing_group`.

Retirement is the destructive catalog operation: retiring an `ACTIVE` spec (any other status yields `ERR_SPEC_NOT_ACTIVE`) moves it to `RETIRED` and cascades. Every shipment using that spec in `DRAFT`, `CLASSIFIED`, or `PACKAGING_VERIFIED` is cancelled, and — caused by each such cancellation — that shipment's shipping paper, if `DRAFT`, `CERTIFIED`, or `UNDER_AMENDMENT`, is voided. Shipments already `DOCUMENTED` or beyond are untouched.

### 3.4. The Shipment Pipeline: Classify, Verify, Certify, Document

A `ShipperComplianceOfficer` opens a shipment under a carrier by naming the `material_id`, the `packaging_spec_id`, the shipper-declared `declared_shipping_name`, the `quantity_kg` in kilograms (which must be greater than 0), and the `declared_value_cents` (at least 0) that the load handling fee will later draw on. Two guards fire at creation: the carrier must be `APPROVED_ACTIVE` — as it must for creating drivers, vehicles, security plans, and vehicle loads as well, each failure yielding `ERR_CARRIER_NOT_ACTIVE` — and the material's `transport_category` must lie within the carrier's `hazmat_categories`, else `ERR_CATEGORY_NOT_AUTHORIZED` (HTTP 409). The shipment starts in `DRAFT` with `driver_id`, `classified_by_user_id`, `pinned_security_plan_id`, and `pinned_security_plan_version` all null.

Classification requires `DRAFT` (`ERR_SHIPMENT_NOT_DRAFT` otherwise) and compares names, not identifiers: the officer's `declared_shipping_name` is normalized — uppercased, trimmed, with inner whitespace collapsed — and must equal the material's `proper_shipping_name` normalized the same way, failing with `ERR_SHIPPING_NAME_MISMATCH` (HTTP 422) when they differ. On success the normalized value is stored as `normalized_shipping_name`, the acting officer's `X-User-ID` is recorded as `classified_by_user_id`, and the shipment moves to `CLASSIFIED`.

Packaging verification requires `CLASSIFIED` (`ERR_SHIPMENT_NOT_CLASSIFIED` otherwise) and walks a four-link chain in a fixed sub-order. First the chosen spec must be `ACTIVE` (`ERR_SPEC_NOT_ACTIVE`); then the material's hazard class must appear in the spec's `authorized_hazard_classes` (`ERR_PACKAGING_CLASS_MISMATCH`); then the material's packing group must be compatible with the spec's `max_packing_group` per the directional rule of §3.3 (`ERR_PACKING_GROUP_INCOMPATIBLE`); and finally `quantity_kg` must not exceed the spec's `max_net_quantity_kg`, with equality allowed (`ERR_QUANTITY_EXCEEDS_CAPACITY`). A verified shipment lands in `PACKAGING_VERIFIED`.

The shipping paper is created against the shipment by an officer supplying `emergency_contact_phone` — the 24-hour emergency response number — along with `emergency_response_summary` and the `shipper_certification_signed` flag; the paper starts in `DRAFT`. Certification requires the paper to be `DRAFT` or `UNDER_AMENDMENT` (`ERR_PAPER_NOT_CERTIFIABLE` otherwise) and the `shipper_certification_signed` flag to be true (a false value fails request-shape validation with `ERR_INVALID_REQUEST`). Segregation of duties is enforced at this step: if the certifying officer's `X-User-ID` equals the shipment's `classified_by_user_id`, the request is rejected with `ERR_SOD_VIOLATION` (HTTP 403). A certified paper records the certifier as `certified_by_user_id`, copies the shipment material's `erg_guide_number` into its `er_response_guide_number`, and moves to `CERTIFIED`.

Documenting the shipment requires `PACKAGING_VERIFIED` (`ERR_SHIPMENT_NOT_PACKAGING_VERIFIED`) and requires the shipment's paper to exist and be `CERTIFIED` (`ERR_PAPER_NOT_CERTIFIED`); success lands the shipment in `DOCUMENTED`. From there a `Regulator` may reject it — only `DOCUMENTED` is rejectable, else `ERR_SHIPMENT_NOT_DOCUMENTED`, optionally supplying a `reason` — which moves the shipment to `REJECTED` and, as the linked consequence, moves its `CERTIFIED` paper to `UNDER_AMENDMENT` with `amendment_count` incremented by 1. The officer then reworks the shipment — only `REJECTED` is reworkable, else `ERR_SHIPMENT_NOT_REJECTED` — returning it to `DRAFT` with `normalized_shipping_name` and `classified_by_user_id` cleared, ready for another pass. A certified paper may also be opened for amendment directly, optionally updating `emergency_contact_phone` or `emergency_response_summary`; amending requires `CERTIFIED` (`ERR_PAPER_NOT_CERTIFIED`) and likewise moves the paper to `UNDER_AMENDMENT` with `amendment_count` incremented, after which it must be re-certified before the shipment can document again.

Cancellation is an officer action available while the shipment is `DRAFT`, `CLASSIFIED`, or `PACKAGING_VERIFIED`, otherwise `ERR_SHIPMENT_NOT_CANCELLABLE`. The voiding side effect on the paper depends on how far the pipeline had progressed: cancelling from `DRAFT` or `CLASSIFIED` voids a paper in `DRAFT` or `UNDER_AMENDMENT`, while cancelling from `PACKAGING_VERIFIED` voids a paper in `DRAFT`, `CERTIFIED`, or `UNDER_AMENDMENT`. Amending a shipment is the second OCC-guarded write (§2.6): the officer supplies `expected_shipment_version` and may change `material_id`, `packaging_spec_id`, `declared_shipping_name`, `quantity_kg`, or `declared_value_cents`. The shipment must be `DRAFT`, `CLASSIFIED`, or `PACKAGING_VERIFIED` (`ERR_SHIPMENT_NOT_AMENDABLE`); a change to any of the four classification-relevant fields — `material_id`, `packaging_spec_id`, `quantity_kg`, or `declared_shipping_name` — reverts the shipment to `DRAFT` and clears `normalized_shipping_name` and `classified_by_user_id`, and every amendment increments the shipment's `version` by 1.

### 3.5. Drivers, Training Records, and Qualification Posture

A `CarrierAdmin` onboards a driver under an `APPROVED_ACTIVE` carrier by supplying `full_name`, `cdl_number` (unique), and `hazmat_endorsement_expires_at`; the driver starts `ACTIVE`. Driver qualification is a computed posture, evaluated on every read and re-evaluated at tender, and refreshed whenever the clock sweeps, a training record is created, or a carrier suspension or reinstatement cascade touches the driver. The posture is decided in order: a driver whose `status` is `SUSPENDED` is `SUSPENDED`; otherwise, when the clock is strictly later than `hazmat_endorsement_expires_at` the posture is `ENDORSEMENT_EXPIRED` — at the exact expiry instant the endorsement is still valid; otherwise, when no training record of the driver has `expires_at` at or after the clock the posture is `TRAINING_LAPSED` — a record expiring exactly now still counts; otherwise the driver is `QUALIFIED`.

Training records are appended by the carrier administrator with a `training_type` of `INITIAL` or `RECURRENT`, a `completed_at` instant, and a free-text `certificate_code`; the record's `expires_at` is computed, never supplied. The computation looks for the latest prior record of the same driver — the one with the greatest `completed_at` strictly before the new record's `completed_at`, ties on equal `completed_at` broken by `created_at` ascending. When such a prior record exists and the new completion falls inside the early-renewal window — the closed interval from ninety days before the prior record's `expires_at` through the prior `expires_at` itself, both bounds inclusive — the new `expires_at` anchors to the prior one: prior `expires_at` plus three years. A completion exactly ninety days before the prior expiry anchors; a completion exactly at the prior expiry anchors; one second after the prior expiry does not. In every other case the new `expires_at` is simply the new `completed_at` plus three years. Each creation also recomputes the driver's posture.

Suspension and reinstatement of drivers are not operator actions at all: they arrive only through the carrier cascade of §3.6, and each transition recomputes `qualification_posture` afterward.

### 3.6. Tendering, Loads, and the Dispatch Cascade

Tendering is the pivotal officer action on a shipment and carries several gates, applied in the system's validation order. The shipment's carrier must be `APPROVED_ACTIVE` first, else `ERR_CARRIER_NOT_ACTIVE`; then the shipment must be `DOCUMENTED` — or already `TENDERED`, since re-tendering is a supported self-loop — else `ERR_SHIPMENT_NOT_DOCUMENTED`. When the material `requires_security_plan`, a security plan must be selectable (below), else `ERR_SECURITY_PLAN_REQUIRED`. The supplied `driver_id` must resolve to a driver of the same carrier as the shipment (a foreign-key failure yields `ERR_INVALID_REFERENCE`), and that driver's `qualification_posture` must be `QUALIFIED` at this instant, else `ERR_DRIVER_NOT_QUALIFIED` (HTTP 409). The fiscal gate comes last among these checks: the carrier's `outstanding_balance_cents` must be exactly 0, else `ERR_OUTSTANDING_FEES` (HTTP 402). A successful tender stores `driver_id` and pins the selected plan's identity and current `version` onto the shipment as `pinned_security_plan_id` and `pinned_security_plan_version` — both null when the material does not require a plan. Re-tendering from `TENDERED` re-runs every gate and re-pins plan and driver.

Plan selection works like this. Candidates are the carrier's plans in `APPROVED` whose `coverage_categories` include the material's `transport_category` and whose window covers the clock with closed bounds — `effective_from` at or before the clock and `effective_to` at or after it. Candidates are ranked by `approved_at` descending, ties broken by `created_at` ascending, and the winner's id and current version are what get pinned. An empty candidate set is the `ERR_SECURITY_PLAN_REQUIRED` failure.

Before any staging can happen, a `CarrierAdmin` registers vehicles under an `APPROVED_ACTIVE` carrier by supplying the `plate_number` (unique per §2.9) and a `vehicle_class` of `VAN`, `FLATBED`, or `TANKER`; a new vehicle starts `AVAILABLE`.

Vehicle loads are staged against a vehicle. Creating one names the `route_id` plus `planned_departure_at` and `planned_arrival_at`, which define a half-open window: the load occupies the vehicle from `planned_departure_at` inclusive up to but not including `planned_arrival_at`. The new load starts `STAGING`; the vehicle must be `APPROVED_ACTIVE`-carrier-owned, and the window must not overlap any other non-terminal load on the same vehicle — with half-open semantics, two windows that merely touch at an endpoint do not conflict. An overlap yields `ERR_LOAD_WINDOW_CONFLICT`. Creating the first non-terminal load on an `AVAILABLE` vehicle moves the vehicle to `LOADING`.

Items join a `STAGING` load — any other state yields `ERR_LOAD_NOT_STAGING` — by naming `shipment_id` and a free-text `position_code`; each resulting `LoadItem` records its parent load as `load_id`. The shipment must be `DOCUMENTED` (`ERR_SHIPMENT_NOT_DOCUMENTED`), must not already sit on another non-terminal load (`ERR_SHIPMENT_ALREADY_LOADED`), and the segregation check runs against the items already aboard (§3.7), rejecting with `ERR_SEGREGATION_VIOLATION` on any forbidden pairing. Each add recomputes the load's `total_table2_weight_kg`: the live sum of `quantity_kg` over the load's current items whose material's `placard_table` is `TABLE_2`, expressed to one decimal, with removed items leaving the sum immediately. Removing an item — the compensating action for an add — is permitted only while the load is `STAGING` and the shipment is still `DOCUMENTED`; a shipment already `TENDERED` cannot be pulled item-wise (it takes a load void, or a carrier suspension, to free it), and the attempt yields `ERR_SHIPMENT_NOT_REMOVABLE`. Removal likewise recomputes the weight.

Suspension of a carrier is the operation with the widest blast radius. When a `Regulator` suspends an `APPROVED_ACTIVE` carrier, three cascades fire in order. First, every `ACTIVE` driver of the carrier moves to `SUSPENDED` — plans are not state-changed by suspension; the tender and dispatch gates already require an `APPROVED_ACTIVE` carrier, which is what makes plans unavailable in practice. Second, as a consequence of the carrier leaving `APPROVED_ACTIVE`, every shipment of the carrier in `TENDERED` reverts to `DOCUMENTED` with `pinned_security_plan_id` and `pinned_security_plan_version` cleared — the assigned `driver_id` is kept. Third, each reverted shipment's load item is removed from any `STAGING` or `SEALED` load; every affected load recomputes `total_table2_weight_kg`, and an affected `SEALED` load falls back to `STAGING` with `required_placards` cleared to the empty list and `handling_fee_cents` zeroed.

Sealing, dispatching, arriving, and voiding complete the load's life; §3.7 covers placard computation and the dispatch gates.

### 3.7. Placards, Segregation, and Dispatch-Day Gates

Sealing a load requires `STAGING` (`ERR_LOAD_NOT_STAGING`), at least one item aboard (`ERR_LOAD_EMPTY`), the vehicle's carrier in `APPROVED_ACTIVE` (`ERR_CARRIER_NOT_ACTIVE`), and a clean segregation check across every pair of items (`ERR_SEGREGATION_VIOLATION`). The segregation rule has two independent grounds. By hazard class, the forbidden unordered pairs are: any of `CLASS_1_1`, `CLASS_1_2`, or `CLASS_1_3` against `CLASS_5_1`; `CLASS_5_1` against `CLASS_3`; and `CLASS_2_3` against `CLASS_3`. By segregation group, the forbidden pairs are `SG_ACID` against `SG_ALKALI`, and `SG_OXIDIZER` against `SG_FLAMMABLE`. The check runs when an item is added (candidate against existing items) and again, over all pairs, at seal.

A successful seal computes and stores three things. The `total_table2_weight_kg` is recomputed. The `required_placards` are determined as follows: every item whose material is `TABLE_1` contributes its material's `hazard_class` label at any quantity; separately, when the aggregate Table-2 weight reaches at least 454.0 kg — the boundary is inclusive — every distinct `hazard_class` among the Table-2 items contributes its label; the required set is the union of those two groups. The DANGEROUS substitution then applies when three conditions hold together: the carrier's `accepts_dangerous_placard_substitution` is true, the Table-2 label set would contain at least two distinct classes, and the aggregate Table-2 weight reaches at least 2270.0 kg, again inclusive; in that case the required set becomes the Table-1 labels union the single label `DANGEROUS`. Finally the `handling_fee_cents` is computed: for each item, the shipment's `declared_value_cents` multiplied by 0.0625 and rounded half-up to whole cents, then summed as integers, plus a flat 725 cents per required placard — each line rounded before summing, never summed then rounded. Unsealing a `SEALED` load (otherwise `ERR_LOAD_NOT_SEALED`) returns it to `STAGING` with `required_placards` cleared to the empty list and `handling_fee_cents` zeroed.

Dispatching is the most heavily gated action in the system. The load must be `SEALED` (`ERR_LOAD_NOT_SEALED`). Every item's shipment must be `TENDERED` (`ERR_SHIPMENT_NOT_TENDERED`). The route's effective window must cover the clock with closed bounds, else `ERR_ROUTE_NOT_EFFECTIVE`; and when the route's `is_restricted_corridor` is true, every item's material hazard class must appear in the route's `allowed_hazard_classes`, else `ERR_ROUTE_RESTRICTED_CLASS` — the corridor check runs only after the window check passes. For every item shipment carrying a `pinned_security_plan_id`, the pinned version must still equal the plan's current `version` and the plan must still be `APPROVED`, else `ERR_STALE_SECURITY_PLAN`; this is where a plan revision stales a pinned shipment, since revising an `APPROVED` plan (§3.8) increments its version. The vehicle's carrier must be `APPROVED_ACTIVE` (`ERR_CARRIER_NOT_ACTIVE`). And the vehicle must be `LOADING` — meaning no other load of that vehicle is currently `DISPATCHED` — else `ERR_VEHICLE_NOT_DISPATCHABLE`.

A successful dispatch fires a three-link cascade: the vehicle moves to `DISPATCHED`; in parallel every item shipment moves from `TENDERED` to `IN_TRANSIT`; and each now-in-transit shipment's `CERTIFIED` shipping paper moves to `LOCKED_IN_TRANSIT`. Arrival requires `DISPATCHED` (`ERR_LOAD_NOT_DISPATCHED`) and reverses the transport state: the load becomes `ARRIVED`, every item shipment moves from `IN_TRANSIT` to `DELIVERED`, and the vehicle returns to `AVAILABLE` unless another non-terminal load remains on it, in which case it stays `LOADING`. Voiding — permitted from `STAGING` or `SEALED`, else `ERR_LOAD_NOT_VOIDABLE` — removes all items, reverts any `TENDERED` item shipment to `DOCUMENTED` (pin fields kept), clears `required_placards` and zeroes both `handling_fee_cents` and `total_table2_weight_kg`, and returns the vehicle to `AVAILABLE` when no other non-terminal load remains.

### 3.8. Security Plans and Route Windows

Security plans belong to carriers and are created by a `CarrierAdmin` with a `plan_name`, the `coverage_categories` this plan covers — a subset of the carrier's authorized categories — and a closed coverage window from `effective_from` through `effective_to`. At creation the window is checked against every other plan of the same carrier that is neither `REJECTED` nor `EXPIRED`: because the intervals are closed, windows that merely touch at an endpoint conflict, and an overlap yields `ERR_PLAN_WINDOW_CONFLICT`. A new plan starts `DRAFT`, and the same carrier-active gate that guards other creations applies here too.

The plan workflow is a submit–approve cycle with a revision loop. Submission moves a plan from `DRAFT` or `UNDER_REVISION` to `SUBMITTED` (any other state yields `ERR_PLAN_NOT_SUBMITTABLE`). A `Regulator` then approves — requiring `SUBMITTED` (`ERR_PLAN_NOT_SUBMITTED`) and re-checking at approval that no other non-terminal plan of the same carrier overlaps the closed window (`ERR_PLAN_WINDOW_CONFLICT`) — which stamps `approved_at` with the clock, increments the plan's `version` by 1, and lands it in `APPROVED`; or rejects it to the terminal `REJECTED` under the same `SUBMITTED` precondition. Revising an `APPROVED` plan requires exactly that state (`ERR_PLAN_NOT_APPROVED`), moves it to `UNDER_REVISION`, and increments `version` by 1 — which is precisely what stales any shipment that pinned the plan at tender, since dispatch compares the pinned version against the current one (§3.7). Like carriers, plans expire only through the clock sweep: an `APPROVED` plan whose `effective_to` is passed becomes `EXPIRED`, a terminal state.

Routes are regulator-created with a `route_code`, the `allowed_hazard_classes` permitted on the corridor, an optional `is_restricted_corridor` flag (default false), and their own closed `effective_from`–`effective_to` window. Windows for the same `route_code` must not overlap, and here too closed-interval semantics mean touching endpoints conflict, yielding `ERR_ROUTE_WINDOW_CONFLICT`.

### 3.9. Incident Reporting and Penalties

When something goes wrong, an officer files an incident report against a shipment, supplying `occurred_at` and a reported `severity` of `MINOR`, `MAJOR`, or `CATASTROPHIC`. The report starts `DRAFT`; its `carrier_id` is denormalized from the shipment at creation, and three computed fields are derived immediately: `phone_report_required` is true exactly when severity is `MAJOR` or `CATASTROPHIC`; `phone_deadline` is twelve hours after `occurred_at`; and `written_report_deadline` is thirty days after `occurred_at`.

The reporting workflow has two filing steps and a close. Recording the phone report requires `DRAFT` (`ERR_INCIDENT_NOT_DRAFT`) and stamps `phone_reported_at` with the clock, moving the report to `PHONE_REPORTED`. Filing the written report requires `PHONE_REPORTED` — with one exception: a `MINOR` report may file directly from `DRAFT`; any other shape yields `ERR_PHONE_REPORT_REQUIRED`. Filing stamps `written_filed_at` with the clock and evaluates both lateness flags: `is_phone_late` is true when a phone report was required and either never happened or was recorded strictly after `phone_deadline` — a phone call recorded exactly at the deadline is on time; `is_written_late` is true when `written_filed_at` is strictly after `written_report_deadline` — filing exactly at the deadline is on time, and the flag is false until filed. Filing also computes the reported penalty variant: a severity base of 0 cents for `MINOR`, 50000 for `MAJOR`, or 150000 for `CATASTROPHIC`; plus 25000 cents when `is_phone_late`; plus a written-lateness component of 5000 cents per full day late, capped at 500000 cents, where days late is the number of whole 86400-second periods by which the filing passed the deadline, never negative.

Closing belongs to the `Regulator`, requires `WRITTEN_FILED` (`ERR_INCIDENT_NOT_CLOSABLE`), and carries the `confirmed_severity` plus an optional `adjustment_percent` between −50 and 50 inclusive. At close the penalty is recomputed as the confirmed variant: the same base and lateness components, but with the base keyed on the confirmed severity, and the whole sum multiplied by one plus `adjustment_percent` hundredths, rounded half-up; the confirmed figure replaces the reported figure in `penalty_cents`. Closing also decrements the carrier's `safety_rating` — 2 points for a confirmed `MINOR`, 10 for `MAJOR`, 25 for `CATASTROPHIC` — with the rating floored at 0, and the report lands in the terminal `CLOSED`.


## 4. Endpoint Definitions

Status-code convention: creating a new resource returns 201; modifying an existing resource (including state transitions, payments, certifications, and clock control) returns 200; list and detail reads return 200. The full request payloads, preconditions, and side effects for each endpoint are specified in §2 and §3 — this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /hazmat/_clock/set_current_utc | Advance the logical clock; fires the expiry sweep and posture refresh | Regulator |
| POST | /hazmat/carriers | Register a new carrier (DRAFT) | CarrierAdmin |
| GET | /hazmat/carriers | List carriers | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| GET | /hazmat/carriers/{carrierId} | Get one carrier | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| POST | /hazmat/carriers/{id}/registration/submit | Submit registration (INITIAL/RENEWAL/early-renewal); OCC-guarded; creates provisional invoice | CarrierAdmin |
| POST | /hazmat/carriers/{id}/registration/approve | Approve a SUBMITTED registration; recompute open invoice at final variant | Regulator |
| POST | /hazmat/carriers/{id}/suspend | Suspend an APPROVED_ACTIVE carrier (cascade: drivers, shipments, loads) | Regulator |
| POST | /hazmat/carriers/{id}/reinstate | Reinstate a SUSPENDED carrier; creates flat REINSTATEMENT invoice | Regulator |
| POST | /hazmat/carriers/{id}/payments | Apply a payment across OPEN invoices via the waterfall | CarrierAdmin |
| GET | /hazmat/carriers/{id}/registration-invoices | List a carrier's registration invoices | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| POST | /hazmat/registration-invoices/{invoiceId}/void | Void an OPEN invoice | Regulator |
| POST | /hazmat/carriers/{id}/security-plans | Create a security plan (DRAFT); closed-window overlap checked | CarrierAdmin |
| GET | /hazmat/carriers/{id}/security-plans | List a carrier's security plans | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| POST | /hazmat/security-plans/{planId}/submit | Submit a plan from DRAFT or UNDER_REVISION | CarrierAdmin |
| POST | /hazmat/security-plans/{planId}/approve | Approve a SUBMITTED plan; re-checks window overlap; bumps version | Regulator |
| POST | /hazmat/security-plans/{planId}/reject | Reject a SUBMITTED plan (terminal) | Regulator |
| POST | /hazmat/security-plans/{planId}/revise | Move an APPROVED plan to UNDER_REVISION; bumps version | CarrierAdmin |
| POST | /hazmat/hazmat-materials | Register a hazmat material in the catalog | Regulator |
| GET | /hazmat/hazmat-materials | List catalog materials | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| POST | /hazmat/packaging-specs | Register an authorized packaging specification (ACTIVE) | Regulator |
| GET | /hazmat/packaging-specs | List packaging specifications | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| POST | /hazmat/packaging-specs/{specId}/retire | Retire an ACTIVE spec; cancels pre-DOCUMENTED shipments and voids their papers | Regulator |
| POST | /hazmat/carriers/{id}/drivers | Onboard a driver | CarrierAdmin |
| GET | /hazmat/carriers/{id}/drivers | List a carrier's drivers | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| GET | /hazmat/drivers/{driverId} | Get one driver (includes qualification posture) | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| POST | /hazmat/drivers/{id}/training-records | Append a training record; expiry computed | CarrierAdmin |
| GET | /hazmat/drivers/{id}/training-records | List a driver's training records | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| POST | /hazmat/carriers/{id}/vehicles | Register a vehicle | CarrierAdmin |
| GET | /hazmat/carriers/{id}/vehicles | List a carrier's vehicles | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| GET | /hazmat/vehicles/{vehicleId} | Get one vehicle | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| POST | /hazmat/carriers/{id}/shipments | Create a shipment (DRAFT); carrier-active and category guards | ShipperComplianceOfficer |
| GET | /hazmat/carriers/{id}/shipments | List a carrier's shipments | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| GET | /hazmat/shipments | Global shipment list with filters | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| GET | /hazmat/shipments/{shipmentId} | Get one shipment | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| PATCH | /hazmat/shipments/{shipmentId} | Amend a shipment; OCC-guarded; classification-relevant edits revert to DRAFT | ShipperComplianceOfficer |
| POST | /hazmat/shipments/{id}/classify | Classify: normalized PSN match against the material | ShipperComplianceOfficer |
| POST | /hazmat/shipments/{id}/verify-packaging | Verify packaging authorization chain | ShipperComplianceOfficer |
| POST | /hazmat/shipments/{id}/document | Document: requires the shipment's paper CERTIFIED | ShipperComplianceOfficer |
| POST | /hazmat/shipments/{id}/reject | Regulator rejection; CERTIFIED paper drops to UNDER_AMENDMENT | Regulator |
| POST | /hazmat/shipments/{id}/rework | Rework a REJECTED shipment back to DRAFT | ShipperComplianceOfficer |
| POST | /hazmat/shipments/{id}/tender | Tender to carrier: driver, plan pin, fiscal gate; re-tender re-pins | ShipperComplianceOfficer |
| POST | /hazmat/shipments/{id}/cancel | Cancel a pre-DOCUMENTED shipment; voids its non-locked paper | ShipperComplianceOfficer |
| GET | /hazmat/shipments/{id}/load-items | List LoadItems referencing this shipment | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| POST | /hazmat/shipments/{id}/shipping-papers | Create the shipment's shipping paper (DRAFT); 1:1 | ShipperComplianceOfficer |
| GET | /hazmat/shipments/{id}/shipping-papers | Get the shipment's shipping papers | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| POST | /hazmat/shipping-papers/{paperId}/certify | Certify a DRAFT or UNDER_AMENDMENT paper; SoD enforced | ShipperComplianceOfficer |
| POST | /hazmat/shipping-papers/{paperId}/amend | Open a CERTIFIED paper for amendment | ShipperComplianceOfficer |
| POST | /hazmat/vehicles/{vehicleId}/loads | Create a load (STAGING); half-open window overlap checked | ShipperComplianceOfficer |
| GET | /hazmat/vehicle-loads | List loads with filters | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| GET | /hazmat/vehicle-loads/{loadId} | Get one load (weight, placards, fee) | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| GET | /hazmat/vehicle-loads/{id}/items | List the load's current LoadItems | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| POST | /hazmat/vehicle-loads/{id}/items | Add a DOCUMENTED shipment to a STAGING load; segregation checked | ShipperComplianceOfficer |
| DELETE | /hazmat/vehicle-loads/{id}/items/{shipmentId} | Remove an item from a STAGING load (shipment DOCUMENTED only) | ShipperComplianceOfficer |
| POST | /hazmat/vehicle-loads/{id}/seal | Seal a STAGING load: segregation, weight, placards, fee | ShipperComplianceOfficer |
| POST | /hazmat/vehicle-loads/{id}/unseal | Unseal a SEALED load back to STAGING | ShipperComplianceOfficer |
| POST | /hazmat/vehicle-loads/{id}/dispatch | Dispatch a SEALED load: route and pin gates; cascades | ShipperComplianceOfficer |
| POST | /hazmat/vehicle-loads/{id}/arrive | Arrive a DISPATCHED load | ShipperComplianceOfficer |
| POST | /hazmat/vehicle-loads/{id}/void | Void a STAGING/SEALED load; TENDERED shipments revert | ShipperComplianceOfficer |
| POST | /hazmat/routes | Create a route; same-code windows must not overlap | Regulator |
| GET | /hazmat/routes | List routes | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| POST | /hazmat/shipments/{id}/incident-reports | File an incident report (DRAFT); deadlines computed | ShipperComplianceOfficer |
| GET | /hazmat/incident-reports | List incident reports with filters | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| GET | /hazmat/incident-reports/{incidentId} | Get one incident report | CarrierAdmin, ShipperComplianceOfficer, Regulator |
| POST | /hazmat/incident-reports/{incidentId}/record-phone-report | Record the phone notification (clock-stamped) | ShipperComplianceOfficer |
| POST | /hazmat/incident-reports/{incidentId}/file-written | File the written report; reported penalty computed | ShipperComplianceOfficer |
| POST | /hazmat/incident-reports/{incidentId}/close | Close: confirmed penalty replaces reported; safety rating decremented | Regulator |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this catalogue is a status-code reference only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_REFERENCE | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_CARRIER_NOT_FOUND | 404 |
| ERR_SECURITY_PLAN_NOT_FOUND | 404 |
| ERR_DRIVER_NOT_FOUND | 404 |
| ERR_VEHICLE_NOT_FOUND | 404 |
| ERR_SHIPMENT_NOT_FOUND | 404 |
| ERR_SHIPPING_PAPER_NOT_FOUND | 404 |
| ERR_LOAD_NOT_FOUND | 404 |
| ERR_INCIDENT_NOT_FOUND | 404 |
| ERR_INVOICE_NOT_FOUND | 404 |
| ERR_CARRIER_NOT_ACTIVE | 409 |
| ERR_CARRIER_NOT_SUBMITTABLE | 409 |
| ERR_CARRIER_NOT_SUBMITTED | 409 |
| ERR_CARRIER_NOT_SUSPENDED | 409 |
| ERR_PLAN_NOT_SUBMITTABLE | 409 |
| ERR_PLAN_NOT_SUBMITTED | 409 |
| ERR_PLAN_NOT_APPROVED | 409 |
| ERR_PLAN_WINDOW_CONFLICT | 409 |
| ERR_SPEC_NOT_ACTIVE | 409 |
| ERR_SHIPMENT_NOT_DRAFT | 409 |
| ERR_SHIPMENT_NOT_CLASSIFIED | 409 |
| ERR_SHIPMENT_NOT_PACKAGING_VERIFIED | 409 |
| ERR_SHIPMENT_NOT_DOCUMENTED | 409 |
| ERR_SHIPMENT_NOT_REJECTED | 409 |
| ERR_SHIPMENT_NOT_CANCELLABLE | 409 |
| ERR_SHIPMENT_NOT_AMENDABLE | 409 |
| ERR_SHIPMENT_NOT_TENDERED | 409 |
| ERR_SHIPMENT_ALREADY_LOADED | 409 |
| ERR_SHIPMENT_NOT_REMOVABLE | 409 |
| ERR_PAPER_NOT_CERTIFIABLE | 409 |
| ERR_PAPER_NOT_CERTIFIED | 409 |
| ERR_DUPLICATE_SHIPPING_PAPER | 409 |
| ERR_LOAD_NOT_STAGING | 409 |
| ERR_LOAD_NOT_SEALED | 409 |
| ERR_LOAD_NOT_DISPATCHED | 409 |
| ERR_LOAD_NOT_VOIDABLE | 409 |
| ERR_LOAD_EMPTY | 409 |
| ERR_LOAD_WINDOW_CONFLICT | 409 |
| ERR_ROUTE_WINDOW_CONFLICT | 409 |
| ERR_ROUTE_NOT_EFFECTIVE | 409 |
| ERR_ROUTE_RESTRICTED_CLASS | 409 |
| ERR_CATEGORY_NOT_AUTHORIZED | 409 |
| ERR_SHIPPING_NAME_MISMATCH | 422 |
| ERR_PACKAGING_CLASS_MISMATCH | 409 |
| ERR_PACKING_GROUP_INCOMPATIBLE | 409 |
| ERR_QUANTITY_EXCEEDS_CAPACITY | 409 |
| ERR_SEGREGATION_VIOLATION | 409 |
| ERR_SECURITY_PLAN_REQUIRED | 409 |
| ERR_STALE_SECURITY_PLAN | 409 |
| ERR_SOD_VIOLATION | 403 |
| ERR_DRIVER_NOT_QUALIFIED | 409 |
| ERR_OUTSTANDING_FEES | 402 |
| ERR_DUPLICATE_USDOT | 409 |
| ERR_DUPLICATE_CDL | 409 |
| ERR_DUPLICATE_PLATE | 409 |
| ERR_DUPLICATE_UN_NA | 409 |
| ERR_DUPLICATE_SPEC_CODE | 409 |
| ERR_INCIDENT_NOT_DRAFT | 409 |
| ERR_PHONE_REPORT_REQUIRED | 409 |
| ERR_INCIDENT_NOT_CLOSABLE | 409 |
| ERR_INVOICE_NOT_VOIDABLE | 409 |
| ERR_VEHICLE_NOT_DISPATCHABLE | 409 |
