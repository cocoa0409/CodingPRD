# EV Battery Warranty & State-of-Health Diagnostics API — Product Requirements Document

## 1. Introduction

An electric-vehicle manufacturer's capacity-retention warranty is a promise measured in two units at once: elapsed months since the car was delivered, and miles on the odometer. Whichever runs out first ends the coverage, and inside the coverage window the promise itself steps down over time — a pack that must hold 80 percent of its beginning-of-life capacity in year four may only have to hold 70 percent in year eight. Honouring that promise at fleet scale is not primarily a payments problem. It is a diagnostics problem: before anybody spends a dollar, the program has to be able to say, defensibly and reproducibly, what a specific pack's state of health actually is, using telemetry that arrives continuously and is frequently unusable.

This API is the system of record for that entire chain. It ingests per-vehicle telematics snapshots and screens each one for plausibility; it turns the surviving snapshots into a signed state-of-health assessment, or refuses to and says why; it decides from the assessment, the pack's module roster and the pack's thermal history whether the correct remedy is a module swap, a whole-pack replacement, or a software flash; it selects a remanufactured replacement pack from regional stock under an explicit eligibility-and-ranking policy; it computes the money, splitting cost between the manufacturer and the owner when the vehicle has slipped into the goodwill band beyond nominal coverage; and it then supervises physical execution inside a certified high-voltage bay by a certified technician using in-calibration tooling.

Two adjacent obligations run through the same data. Thermal events on high-voltage packs carry containment procedures and hard regulatory filing deadlines, and a late filing is an auditable compliance failure that damages a service center's standing and can decertify it. Removed packs are hazardous freight whose classification, packaging, state-of-charge cap and transport mode are dictated by whether the pack is damaged, and whose shipper certification must be signed by somebody other than the technician who pulled the pack out of the car. Owners who dispute a capacity measurement are entitled to independent laboratory verification, and a lab result that materially contradicts the manufacturer's own measurement can reopen a denial or collapse an approval. The requirements below specify all of this as one coherent, ordered, auditable system.

## 2. Global Specifications & System-Wide Principles

Everything in this section applies across the whole API surface. Where a rule here and a rule in Section 3 both bear on an operation, both are enforced; Section 3 never relaxes anything stated here.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares the capacity in which it is acting. If `X-User-Role` is absent, or carries a string that is not one of the seven recognised roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognised but is not among the roles authorised for the target operation, the rejection is `ERR_UNAUTHORIZED` (HTTP 403). A third, narrower rule covers actor attribution: on the operations that persist who performed them — claim adjudication, claim fulfilment, dispute resolution, shipment tender, and the recording of an owner's consent decision — a missing `X-User-ID` header is rejected with `ERR_ACTOR_REQUIRED` (HTTP 400) even when the role itself is acceptable.

The seven roles are `ProgramAdmin`, `WarrantyAdjudicator`, `ServiceTechnician`, `TelematicsGateway`, `VehicleOwner`, `IndependentLab`, and `RegulatoryLiaison`. Spelling is exact and case-sensitive.

- A `ProgramAdmin` is the OEM battery-program administrator. It configures warranty programs, registers vehicles, service centers, technicians and battery packs, creates and releases remediation campaigns, solicits owner consent, records receipt of returned packs, and drives the logical clock.
- A `WarrantyAdjudicator` opens information requests on claims, decides them, closes them, and resolves capacity disputes raised against decisions made by *other* adjudicators.
- A `ServiceTechnician` runs diagnostics, files and resubmits claims, executes approved remedies inside a booked high-voltage bay, records thermal containment steps, applies software flashes, and creates and tenders removed-pack shipments.
- A `TelematicsGateway` is the vehicle telemetry ingestion channel. It is the only producer of telematics snapshots and a co-producer, alongside `ServiceTechnician`, of thermal-event reports.
- A `VehicleOwner` grants or declines a software remediation flash on their own vehicle and files capacity disputes against their own claims.
- An `IndependentLab` is the only producer of laboratory capacity measurements on a dispute.
- A `RegulatoryLiaison` is the only role permitted to file a thermal-event notification with the regulator.

Read access is broad: every retrieval operation in this API is available to every role, with the single exception that `TelematicsGateway` may read only vehicles' telematics snapshots and thermal events.

Identity binding differs by role, and it determines what ownership means for each one.

When `X-User-Role` is `ServiceTechnician`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on any resource that references a `Technician` compare the resource's technician reference to `X-User-ID`. Concretely, filing a claim requires `X-User-ID` to equal the `diagnosing_technician_id` in the payload, resubmitting requires it to equal the claim's stored `diagnosing_technician_id`, and fulfilling requires it to equal the `fulfilment_technician_id` in the payload.

When `X-User-Role` is `VehicleOwner`, `X-User-ID` is the `id` of the acting `Vehicle`; ownership checks on any resource that references a `Vehicle` compare the resource's vehicle reference to `X-User-ID`. Recording a consent decision requires `X-User-ID` to equal the consent's `vehicle_id`, and filing a capacity dispute requires `X-User-ID` to equal the target claim's `vehicle_id`.

When `X-User-Role` is `ProgramAdmin`, `WarrantyAdjudicator`, `TelematicsGateway`, `IndependentLab` or `RegulatoryLiaison`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — an adjudication writes it to the claim's `adjudicated_by_user_id`, and a dispute resolution writes it to the dispute's `resolved_by_user_id` — but it never compares it to any entity's `id`. Both of those recorded values are opaque adjudicator identifiers, so the two-person rule described in Section 2.11 is a plain value comparison between two strings, never an entity lookup.

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

List retrievals accept two query parameters. `limit` caps the number of records returned; when omitted it defaults to 10, and a supplied value must be at least 1 and at most 100. `offset` is the number of records to skip and defaults to 0.

Unless a specific list states otherwise, records come back ordered by `created_at` ascending. Two lists deliberately differ and say so in their own descriptions: a vehicle's telematics snapshots come back newest `captured_at` first, and a pack's modules come back in ascending `position_index` order.

Every list response repeats `limit` and `offset` in the `meta` object alongside `total_count` (the number of records matching the filter before pagination) and `has_more` (true when records remain beyond the current page).

### 2.4. Resource Identity, Audit Fields and the Logical Clock

Each stored record carries an `id`, which is a server-minted UUID with no type prefix and no client-supplied component. Alongside it, most records carry three further system-managed fields: `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the record was first written; `updated_at`, an ISO 8601 UTC timestamp in the same format recording the most recent mutation; and `version`, an integer that starts at 1 and increments by one on every mutation of that record. Recomputing a derived field counts as a mutation: when an adjudication raises a program's `accrued_liability_cents`, or a rejected shipment raises a center's `open_hazmat_holds`, that program record and that center record each refresh `updated_at` and increment `version`. A refresh that recomputes the figure already stored is not a mutation, however: the program, pack, campaign and vehicle mirrors of sections 2.9 and 3.2 leave `updated_at` and `version` alone when the recomputed value matches the stored one, whereas a center's hazmat-hold bookkeeping stamps the center on every step as section 2.9 describes.

`TelematicsSnapshot` is the one exception. A snapshot is an immutable event row: it carries `id` and `created_at` only. It has no `updated_at`, no `version`, and no operation that modifies it after ingestion. Every other entity in this system — warranty programs, vehicles, battery packs, battery modules, state-of-health assessments, service centers, technicians, warranty claims, thermal events, remediation campaigns, remediation consents, capacity disputes and pack shipments — carries the full set of four.

All time-dependent behaviour in this API reads a **logical clock**, never the host's wall clock. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `ProgramAdmin` may advance it to a supplied instant through an administrative test-driving capability; the clock never rewinds, and a request naming an instant earlier than the current one is refused with `ERR_CLOCK_REWIND_FORBIDDEN` (HTTP 409). Setting the clock to the instant it already holds is permitted. Regulatory filing deadlines, snapshot freshness windows, consent expiry, dispute windows, technician certification lapse, insulation-tester calibration expiry and the technician cooldown are all evaluated against this logical clock, with datetime comparisons carried out at millisecond resolution in UTC.

Advancing the clock does not rewrite stored rows in place, but two things are re-derived on their next read: a `Technician`'s `status`, which reads `CERT_LAPSED` whenever `cert_expires_at` is at or before the logical clock and `ACTIVE` otherwise, and the freshness of any snapshot window a later assessment would build.

### 2.5. Money, Percentages and Rounding Discipline

Every monetary amount in this system is an integer count of cents. There are no fractional cents anywhere in a stored value or a response body. Where a money figure is the product of a fractional quantity and a rate — labour hours multiplied by an hourly rate, or a hazardous-materials surcharge basis scaled by a shipping weight — the product is rounded half up to a whole number of cents.

The rounding *order* matters and is fixed. A remedy cost estimate is assembled from four separate line items; each line is rounded to whole cents on its own, and only then are the four rounded lines added together. The alternative reading — summing the raw products and rounding once at the end — is explicitly rejected, because the two readings diverge whenever two fractional lines each round down while their fractional parts together reach one half or more.

Non-monetary quantities have their own fixed scales, and every one of them rounds half up:

- Capacities in kilowatt-hours — `nominal_capacity_kwh`, `reported_capacity_kwh`, `corrected_capacity_kwh`, `module_capacity_kwh`, `bench_measured_capacity_kwh`, `estimated_capacity_kwh`, `nominal_basis_kwh` and `lab_measured_capacity_kwh` — carry three decimal places.
- Shipping weights in kilograms — a pack's `gross_weight_kg` and a shipment's declared `gross_weight_kg` — carry three decimal places.
- Retention and state-of-health percentages — `retention_pct`, `applicable_min_retention_pct`, `min_retention_pct`, `refurb_soh_pct`, `reman_min_soh_pct`, `pack_replacement_retention_pct`, `oem_retention_pct`, `lab_retention_pct`, `deviation_pct`, `lab_tolerance_pct`, `state_of_charge_pct` and `soc_limit_pct` — carry two decimal places.
- `proration_factor` carries four decimal places.
- Counters, millivolt readings, month counts, mile counts and the compliance score are whole integers.

Comparisons happen at the stored precision. A threshold test written as "at or below" admits the boundary value exactly; a threshold test written as "strictly below" does not. Section 3 states the direction for every threshold individually, and those statements are authoritative.

### 2.6. Optimistic Concurrency on Parent Records

Three creation operations write a child record whose meaning depends on a parent record the client must have read first. Each of them therefore requires a version token in its payload, and the field is required, not optional.

Creating a state-of-health assessment requires `expected_vehicle_version` carrying the client's last observed `version` of the target `Vehicle`. If it does not equal that vehicle's current `version`, the create is rejected with `ERR_STALE_VEHICLE_VERSION` (HTTP 412). The protection is not cosmetic: a new assessment legitimately marks every earlier assessment on the same vehicle as superseded, so a writer holding a stale view of the vehicle would silently invalidate a diagnostic it never saw — including one produced after a telematics ingest moved the vehicle's `odometer_miles`.

Filing a capacity dispute requires `expected_claim_version` carrying the client's last observed `version` of the target `WarrantyClaim`. A mismatch with the claim's current `version` is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412). The dispute snapshots the claim's settlement basis at filing time, so a stale view would freeze a basis that no longer describes the claim the owner meant to dispute.

Creating a remediation consent requires `expected_campaign_version` carrying the client's last observed `version` of the target `RemediationCampaign`. A mismatch with the campaign's current `version` is rejected with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412). Each re-solicitation supersedes a declined or expired record and raises the campaign's `open_consent_count`, so a writer with a stale campaign view could otherwise re-open a campaign that has since been suspended or closed.

No other operation in this API takes a version field, and no other operation performs a version check. Every other write is applied against current server state.

### 2.7. Resolution Order and the Precedence of Rejections

Requests that address a resource through a URL path are resolved strictly left to right, and the outermost unresolved segment wins. A request naming a technician under a service center that does not exist is refused with `ERR_CENTER_NOT_FOUND` before the technician segment is examined at all; a request naming modules under a non-existent pack is refused with `ERR_PACK_NOT_FOUND`. The same discipline applies to foreign keys supplied in a request body: they are resolved in the order their fields are declared on the owning entity, so the first unresolvable reference determines the error. The ten path-and-body existence failures are `ERR_PROGRAM_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_PACK_NOT_FOUND`, `ERR_CENTER_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND` and `ERR_SHIPMENT_NOT_FOUND`, each HTTP 404.

More broadly, when several checks bear on one request the outcome is deterministic: checks are evaluated in a single fixed global order, and the first one that fails is the one reported. The governing principle of this domain is that **safety always precedes money** — a fiscal ceiling can never mask a certification, containment or segregation failure, because the fiscal ceiling is checked last. The complete order is:

1. Role authentication — `ERR_UNAUTHENTICATED`.
2. Role authorisation for the target operation — `ERR_UNAUTHORIZED`.
3. Actor attribution on the five operations that persist an actor identity — `ERR_ACTOR_REQUIRED`.
4. Request shape on every write: required inputs present and non-null, enum values inside their declared sets, integers non-negative where constrained, decimals within their declared scale, arrays carrying the declared element type — `ERR_INVALID_REQUEST`.
5. The conditional bench-capacity rule on assessment creation — `ERR_BENCH_CAPACITY_REQUIRED`.
6. Existence of every path-parameter resource, left to right.
7. Existence of every foreign key carried in a request body.
8. `expected_vehicle_version` on assessment creation — `ERR_STALE_VEHICLE_VERSION`.
9. `expected_claim_version` on dispute filing — `ERR_STALE_CLAIM_VERSION`.
10. `expected_campaign_version` on consent creation — `ERR_STALE_CAMPAIGN_VERSION`.
11. `vin` uniqueness on vehicle registration — `ERR_DUPLICATE_VIN`.
12. `serial_number` uniqueness on pack registration — `ERR_DUPLICATE_PACK_SERIAL`.
13. `campaign_code` uniqueness on campaign creation — `ERR_DUPLICATE_CAMPAIGN_CODE`.
14. The no-rewind rule on the logical clock — `ERR_CLOCK_REWIND_FORBIDDEN`.
15. `detected_at` not later than the logical clock on thermal-event reporting — `ERR_DETECTED_AT_IN_FUTURE`.
16. Terminal lockdown: no operation of any kind is accepted against a claim already `CLOSED` — `ERR_CLAIM_TERMINAL`. This guard fronts every claim-scoped operation: information request, resubmit, adjudicate, fulfil and close alike.
17. Claim status `SUBMITTED` for an adjudication or an information request — `ERR_CLAIM_NOT_ADJUDICABLE`.
18. Claim status `INFO_REQUESTED` for a resubmit — `ERR_INFO_REQUEST_NOT_OPEN`.
19. Claim status among `APPROVED_MODULE`, `APPROVED_PACK` and `APPROVED_SOFTWARE` for a fulfilment — `ERR_CLAIM_NOT_FULFILLABLE`.
20. Claim status `FULFILLED` or `DENIED` for a close — `ERR_CLAIM_NOT_CLOSABLE`.
21. Claim status among `APPROVED_MODULE`, `APPROVED_PACK`, `APPROVED_SOFTWARE`, `DENIED` and `FULFILLED` for a dispute filing — `ERR_CLAIM_NOT_DISPUTABLE`.
22. Dispute status `LAB_ASSIGNED` or `LAB_RESULT_RECEIVED` for both lab-result recording and resolution — `ERR_DISPUTE_RESOLVED`.
23. Dispute status exactly `LAB_RESULT_RECEIVED` for a resolution — `ERR_LAB_RESULT_REQUIRED`.
24. Containment-step ordering, and the closing step's dependency on the regulatory dimension — `ERR_CONTAINMENT_STEP_OUT_OF_ORDER` and `ERR_NOTIFICATION_STILL_PENDING`.
25. Notification status `PENDING` for a regulatory filing — `ERR_NOTIFICATION_ALREADY_FILED`.
26. Campaign status `LIMITED_RELEASE` or `FIELD_RELEASE` for consent solicitation — `ERR_CAMPAIGN_NOT_RELEASED`.
27. Consent status `PENDING` for an owner decision — `ERR_CONSENT_ALREADY_DECIDED`.
28. Consent status `GRANTED` for a recorded flash — `ERR_CONSENT_NOT_GRANTED`.
29. Vehicle status `ACTIVE` for all three consent operations — solicitation, decision and flash — `ERR_VEHICLE_IMMOBILIZED`.
30. The backing assessment not superseded, on claim filing — `ERR_ASSESSMENT_SUPERSEDED`.
31. The backing assessment not already cited by a non-closed claim, on claim filing — `ERR_ASSESSMENT_ALREADY_CLAIMED`.
32. The backing assessment's diagnostic verdict `VALID`, on claim filing — `ERR_DIAGNOSTIC_NOT_VALID`.
33. Pack status `REMOVED` or `QUARANTINED` for shipment creation — `ERR_SHIPMENT_PACK_NOT_REMOVED`.
34. Shipment status `DRAFT` for a tender and `TENDERED` for a receipt — `ERR_SHIPMENT_NOT_TENDERED`.
35. Origin center status `ACTIVE` for both shipment creation and tender — `ERR_CENTER_SHIPPING_SUSPENDED`.
36. Pack-to-vehicle coherence on both assessment creation and thermal-event reporting — `ERR_PACK_VEHICLE_MISMATCH`.
37. Assessment-to-claim vehicle coherence on claim filing — `ERR_ASSESSMENT_VEHICLE_MISMATCH`.
38. Technician-to-center coherence on claim filing, fulfilment and shipment creation — `ERR_TECHNICIAN_CENTER_MISMATCH`.
39. Campaign targeting coherence on consent creation — `ERR_VEHICLE_NOT_TARGETED`.
40. An explicitly named replacement pack's region and module count on adjudication — `ERR_PACK_REGION_MISMATCH`.
41. Center status `ACTIVE` at fulfilment — `ERR_CENTER_NOT_CERTIFIED`.
42. Center high-voltage certification level sufficient for the approved remedy — `ERR_CENTER_CERT_LEVEL_INSUFFICIENT`.
43. Certified pack lift present for a pack replacement — `ERR_PACK_LIFT_REQUIRED`.
44. Insulation-tester calibration in date for any hardware fulfilment — `ERR_INSULATION_TESTER_OVERDUE`.
45. Fulfilling technician's certification unexpired, on fulfilment and on shipment tender — `ERR_TECHNICIAN_CERT_EXPIRED`.
46. Fulfilling technician's certification level sufficient for the approved remedy — `ERR_TECHNICIAN_LEVEL_INSUFFICIENT`.
47. Thermal containment closed on the claim's pack before any fulfilment — `ERR_THERMAL_CONTAINMENT_OPEN`.
48. The two-person rules, on dispute resolution and on shipment creation — `ERR_SEGREGATION_OF_DUTIES`.
49. The remedy-downgrade safety lock on adjudication — `ERR_REMEDY_OVERRIDE_FORBIDDEN`.
50. Air transport forbidden for a damaged-pack classification, at shipment creation — `ERR_AIR_TRANSPORT_FORBIDDEN`.
51. Packaging conformance at tender — `ERR_PACKAGING_NONCONFORMANT`.
52. State-of-charge cap at tender — `ERR_SOC_LIMIT_EXCEEDED`.
53. Bay window well-formedness at fulfilment — `ERR_INVALID_BAY_WINDOW`.
54. Bay capacity at fulfilment — `ERR_HV_BAY_CAPACITY_EXCEEDED`.
55. Technician cooldown at fulfilment — `ERR_TECHNICIAN_COOLDOWN_CONFLICT`.
56. Consent not past its expiry, on both the owner decision and the recorded flash — `ERR_CONSENT_EXPIRED`.
57. Dispute filed inside the program's dispute window — `ERR_DISPUTE_WINDOW_EXPIRED`.
58. Module position arrays well-formed on assessment creation — `ERR_MODULE_POSITION_INVALID`.
59. The target vehicle has no pack installed, when a pack is registered as already installed — `ERR_VEHICLE_ALREADY_HAS_PACK`.
60. The vehicle has no non-closed claim, on claim filing — `ERR_CLAIM_ALREADY_OPEN`.
61. Retention at or below the applicable threshold, on claim filing — `ERR_RETENTION_ABOVE_THRESHOLD`.
62. Coverage position not out of coverage, on claim filing — `ERR_OUT_OF_COVERAGE`.
63. The information-request round limit — `ERR_INFO_REQUEST_LIMIT_EXCEEDED`.
64. No duplicate active consent for the campaign-and-vehicle pair, and a well-formed supersession reference — `ERR_DUPLICATE_ACTIVE_CONSENT`.
65. No duplicate active dispute on the claim — `ERR_DUPLICATE_ACTIVE_DISPUTE`.
66. The event is reportable at all, on a regulatory filing — `ERR_NOTIFICATION_NOT_REQUIRED`.
67. An explicitly named replacement pack is free stock of acceptable health — `ERR_PACK_NOT_IN_STOCK`.
68. The replacement-pack selector found a candidate — `ERR_NO_REMAN_PACK_AVAILABLE`.
69. The program liability ceiling — `ERR_LIABILITY_CAP_EXCEEDED`.
70. A limited-scope campaign release names at least one pilot region — `ERR_INVALID_REQUEST`.

Each of these conditions is stated in full, with its trigger, in the Section 3 narrative for the workflow it guards. The catalogue in Section 5 lists identifiers and HTTP statuses only.

### 2.8. Cascade Integrity Across the Program Graph

Records in this system are densely cross-referenced, and several single operations legitimately mutate four or five records at once. The server performs those propagations itself, in the stated order, without requiring the client to issue a follow-up request against any of the affected records. Two long cascades recur often enough to name.

The **thermal cascade** fires when a severity `S3` or `S4` thermal event is reported. First the referenced pack is marked as damaged and defective, is reclassified as `UN3536` hazardous freight, and moves from `IN_SERVICE` to `QUARANTINED`. Because the pack entered `QUARANTINED`, the vehicle it sits in has `warranty_hold` set to true and moves from `ACTIVE` to `IMMOBILIZED`. Because that vehicle became `IMMOBILIZED`, every remediation consent on it whose status is `PENDING` or `GRANTED` moves to `EXPIRED`. Because those consents left the open set, every campaign that held one recomputes its `open_consent_count` and, if that count reaches zero while the campaign is in `LIMITED_RELEASE` or `FIELD_RELEASE`, the campaign itself moves to `CLOSED`. For severity `S4` there is one further step, and its position in the sequence matters: the campaign-suspension check runs *before* the consent-expiry step, and a campaign that has been suspended never auto-closes afterwards.

The **shipment-rejection cascade** fires when a tendered shipment is received and rejected. The pack is set to `QUARANTINED` — from `REMOVED`, or from `QUARANTINED` again if it already stood there — marked damaged and reclassified `UN3536`. The origin center's `open_hazmat_holds` then rises by one on every rejection, with no exemption for a pack that was already quarantined before the rejection. If that brings `open_hazmat_holds` to two or more while the center is `ACTIVE`, the center moves to `SHIPPING_SUSPENDED`. Because the center became `SHIPPING_SUSPENDED`, every warranty claim booked to that center whose status is `APPROVED_MODULE` or `APPROVED_PACK` has `fulfilment_blocked` set to true. Separately and in the same operation, the center's `rejected_shipment_count` rises by one and its `compliance_score` is recomputed.

Suspension is reversible without administrative action. When a re-tendered pack is finally received and `open_hazmat_holds` falls to one or fewer while the center is `SHIPPING_SUSPENDED`, the center returns to `ACTIVE`, and every claim at that center carrying `fulfilment_blocked` true has the flag cleared. Decertification, by contrast, is terminal: a center whose `compliance_score` falls to 20 or below moves to `DECERTIFIED` — from `ACTIVE` or from `SHIPPING_SUSPENDED` alike — and every claim at that center whose status is not `DENIED` and not `CLOSED` has `fulfilment_blocked` set to true. A `DECERTIFIED` center never returns.

### 2.9. Ledger Mirrors and Inventory Mirrors

Two fields on a warranty program are mirrors of aggregate state elsewhere, and both are invariants rather than incrementally maintained tallies. `accrued_liability_cents` must at all times equal the sum of `oem_total_cents` across that program's claims whose `adjudication_status` is one of `APPROVED_MODULE`, `APPROVED_PACK`, `APPROVED_SOFTWARE`, `FULFILLED` or `CLOSED`. `reman_available_count` must at all times equal the number of battery packs whose `pack_type` is `REMANUFACTURED` and whose `status` is `STOCK`. Derived from the second, `reman_stock_state` reads `DEPLETED` when `reman_available_count` is zero and `AVAILABLE` otherwise; a freshly created program starts with both counters at zero and therefore reads `DEPLETED`.

The practical consequence is that every event which changes the underlying population must move the mirror in the same operation. An approval adds the claim's `oem_total_cents`; a denial adds nothing; a dispute-driven remedy change subtracts the old figure before adding the recomputed one; a consent decline on a software approval subtracts the reversed figure. Registering a remanufactured pack into stock raises `reman_available_count`; reserving one for an approved pack replacement lowers it; releasing a reservation back to stock raises it again; and receiving a returned pack for remanufacture raises it. Each such change refreshes the program's `updated_at` and increments its `version`.

A service center carries a comparable set of derived counters. `open_hazmat_holds` is not re-derived from the pack table but carried as a running tally: it starts at zero, rises by one on each rejected receipt and at the pack-quarantine containment step of a thermal event whose pack has an origin center of record, and falls by one — floored at zero — when a shipment of an already-quarantined pack is accepted. A pack that already stands `QUARANTINED` when a further shipment of it is rejected raises the tally just the same, so the figure is a count of holds opened and closed rather than of packs presently in quarantine, and every raising or lowering step refreshes the center record even where the floored figure does not move. `rejected_shipment_count` is the lifetime number of that center's shipments that reached `REJECTED`. `late_notification_count` is the lifetime number of thermal-event notifications the center filed after the deadline. From those two lifetime counters the `compliance_score` is recomputed — never decremented in place — as one hundred, less fifteen for each rejected shipment, less forty for each late notification, with the result floored at zero. Because the score is recomputed from the counters on every change, repeated recomputation is idempotent and cannot drift. Immediately after each recomputation, a score of 20 or below decertifies the center. One late filing at a center with no rejected shipments yields a score of 60 and does not decertify it. A center's counters are strictly its own and are never shared with another center, even when one center's technician works a claim booked to a different center.

### 2.10. High-Voltage Certification, Tooling and Bay Governance

Working inside a high-voltage battery pack is gated on four independent things: the center's certification tier, the center's tooling, the individual technician's certification, and the availability of a physical isolation bay.

Certification tiers are ordinal: `L1` is lower than `L2`, which is lower than `L3`. A center's tier lives in `hv_certification_level`; a technician's personal tier lives in `hv_cert_level`. A pack replacement demands `L3` from both the center and the technician. A module replacement demands `L2` or better from both. A software remediation demands no particular tier from the center and only `L1` or better from the technician who records the flash. Beyond tier, a center must own a certified pack lift, recorded in `has_pack_lift`, before it may execute a pack replacement, and its insulation resistance tester's calibration expiry, `insulation_tester_cal_due_at`, must be strictly later than the logical clock for any hardware remedy. A technician's `cert_expires_at` must likewise be strictly later than the logical clock; at or past that instant the technician's derived `status` reads `CERT_LAPSED` and they may neither fulfil a claim nor certify a hazardous shipment.

Bay occupancy is an interval problem with **half-open** semantics. A fulfilment books a window running from `hv_bay_window_start` up to but not including `hv_bay_window_end`. Two windows conflict exactly when the earlier one's start falls before the later one's end *and* the later one's start falls before the earlier one's end; back-to-back windows that merely touch at an instant, where one ends exactly as the next begins, do not conflict. The capacity rule is aggregate, not pairwise: the number of already-booked windows at the center that overlap the requested window is compared against the center's `hv_bay_count`, and the request is refused only when that overlapping count has reached the bay count. A center with two bays therefore tolerates exactly one concurrent neighbour and refuses the third overlapping window. Only claims already in `FULFILLED` or `CLOSED` occupy a bay; claims in `SUBMITTED`, `INFO_REQUESTED`, any of the approved states, or `DENIED` hold no bay even if bay-window values were echoed onto them, and they are excluded from the overlap count.

Technician rest is a different geometry — a single-resource, exclusive rule rather than an aggregate one. Each technician carries `last_hv_window_end_at`, the end of the most recent window they worked, null before their first. A new window's start must fall at or after that high-water mark plus sixty minutes; starting exactly sixty minutes after the previous window's end is accepted. Only the acting technician's own high-water mark is consulted — other technicians at the same center are irrelevant, and the center's other claims are not scanned. On success, the technician's `last_hv_window_end_at` is raised to whichever is later, its existing value or the new window's end.

### 2.11. Segregation of Duties

Two duties in this program must be performed by different people, and both are enforced as hard rejections with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

The first governs disputes. The `X-User-ID` resolving a capacity dispute must differ from the `adjudicated_by_user_id` recorded on the underlying claim: an adjudicator may not sit in review of their own decision. Both values are opaque `WarrantyAdjudicator` identifiers, so the rule is a straight string comparison and involves no entity lookup.

The second governs hazardous shipping. A shipment's `certifying_technician_id` must differ from the `fulfilment_technician_id` of the claim that removed the pack being shipped: the technician who pulled a pack out of a car may not also sign the hazmat shipper certification for it. Both values are `Technician` identifiers, consistent with the entity-backed identity of the `ServiceTechnician` role.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program: Warranty Terms, Fleet and Service Network

Everything begins with a **warranty program**, the configuration record that carries the commercial terms an entire model-year fleet is judged against. A `ProgramAdmin` registers one by supplying a `name` — something like "MX Battery Capacity Retention 2020". Every other term carries a reference default drawn from the OEM price book, so a program can be stood up from the name alone and then tuned one constant at a time.

The two coverage horizons are `coverage_months`, a whole number of months counted from the vehicle's first retail delivery and constrained to between 60 and 144 months with a default of 96 — eight years — and `coverage_miles`, an odometer distance constrained to between 50,000 and 200,000 miles with a default of 100,000. Inside those horizons the retention promise steps down through `retention_schedule`, an ordered list of between one and four tier rows. Each row is an object carrying `through_months`, `through_miles` and `min_retention_pct`, the last of which must lie between 50.00 and 95.00 with two decimals. The server sorts the supplied rows ascending by `through_months` at write time and persists them in that order, so downstream tier selection can rely on the stored order. The final row must close the schedule exactly: its `through_months` must equal `coverage_months` and its `through_miles` must equal `coverage_miles`. The default schedule is two rows — 80.00 percent retention through 48 months and 50,000 miles, then 70.00 percent through 96 months and 100,000 miles.

Beyond the schedule, a program carries the thresholds that steer remedy choice and the prices that value it. `pack_replacement_retention_pct`, defaulting to 60.00, is the retention percentage strictly below which a whole-pack replacement is mandated instead of a module swap. `module_replacement_cap`, defaulting to 3, is the lifetime ceiling on modules replaced in one pack before the pack must be replaced whole. `cell_delta_pack_threshold_mv`, defaulting to 250 millivolts — a quarter of a volt of spread between the best and worst cell — is the worst-cell voltage spread at or above which pack replacement is likewise mandated. Past the nominal horizons there is a goodwill extension: `goodwill_months`, defaulting to 12, and `goodwill_miles`, defaulting to 15,000, define a band in which the program still pays but shares cost with the owner. `liability_cap_cents` is the ceiling on the program's total accrued exposure and defaults to 50,000,000 cents, that is half a million dollars. `info_request_limit`, defaulting to 2, caps how many times an adjudicator may send one claim back for more information. `lab_tolerance_pct`, defaulting to 2.00, is the absolute number of retention percentage points by which an independent laboratory's measurement may differ from the manufacturer's before the difference is treated as material. `dispute_window_days`, defaulting to 30, is how long after adjudication an owner may still file a dispute, and its boundary day counts as inside the window.

The price book is a set of integer cent amounts and two labour figures. `diagnostic_fee_cents`, defaulting to 12,000 cents, is a flat diagnostic line added to every remedy cost estimate. `module_unit_price_cents` defaults to 145,000 cents for one replacement module. A replacement pack costs `pack_price_new_cents`, defaulting to 1,420,000 cents when factory-new, or `pack_price_reman_cents`, defaulting to 890,000 cents when remanufactured. `labor_hours_module` and `labor_hours_pack` are flat-rate labour allowances, defaulting to 3.25 and 6.50 hours respectively. Three hazardous-materials surcharge bases are quoted per 100 kilograms of shipped weight: `surcharge_un3480_cents` at 4,000 cents for a standalone lithium-ion pack, `surcharge_un3481_cents` at 2,500 cents for modules contained in equipment, and `surcharge_un3536_cents` at 18,000 cents for damaged or defective goods — more than four times the standalone rate, reflecting how much more expensive damaged high-voltage freight is to move.

Three further constants configure the telematics side of the diagnostic. `snapshot_freshness_days`, defaulting to 30, sets how far back a snapshot may have been captured and still count as fresh. `snapshot_window_size`, defaulting to 5, caps how many fresh snapshots the fleet-telemetry estimate consumes. `snapshot_min_count`, defaulting to 3, is the minimum number of fresh valid snapshots a fleet-telemetry assessment requires before it will produce a number at all. Finally, `reman_min_soh_pct`, defaulting to 85.00, is the minimum post-refurbishment state of health a remanufactured pack must carry to be selectable as a replacement, and `allow_new_pack_substitution`, defaulting to false, decides whether an empty remanufactured candidate pool may fall back on factory-new stock instead of failing.

A new program's two mirrors both start at zero — `accrued_liability_cents` at zero and `reman_available_count` at zero — and `reman_stock_state` therefore reads `DEPLETED`.

Vehicles come next. Registering one requires a `vin` of exactly seventeen uppercase alphanumeric characters, unique across the whole fleet — a collision is refused with `ERR_DUPLICATE_VIN` — together with `warranty_program_id` naming the governing program and `in_service_date`, the first-retail-delivery instant that anchors the elapsed-months clock and which must not be later than the current logical clock. Three optional descriptors follow: `model_code`, defaulting to "MX-90" and used to match remediation campaigns; `region_code`, defaulting to "US-WEST" and used for limited-release campaign eligibility; and `owner_contact_email`, defaulting to "owner@example.com", the address consent solicitations are sent to. An `odometer_miles` figure may also be supplied at registration, where it is validated as a non-negative integer and then discarded, because the field is wholly derived: it holds the highest `odometer_miles` seen across that vehicle's snapshots whose validity flag reads `VALID`, and reads 0 while the vehicle has no valid snapshot at all — so a newly registered vehicle reads 0 whatever mileage the registration carried. A freshly registered vehicle is `ACTIVE`, holds no pack — its `installed_pack_id` mirror is null — and carries `warranty_hold` false.

**Battery packs** are registered independently of vehicles. A pack needs a `serial_number` unique across the program, with a collision refused as `ERR_DUPLICATE_PACK_SERIAL`. Its `pack_type` is either `NEW` for factory packs or `REMANUFACTURED` for refurbished stock, defaulting to `NEW`. Its `nominal_capacity_kwh` is the beginning-of-life usable capacity in kilowatt-hours, must be greater than zero, and defaults to 80.000. Its `module_count` must lie between 8 and 24 and defaults to 16. `gross_weight_kg` is the shipping gross weight of the whole pack, defaulting to 483.296, and is the basis of every hazmat surcharge line. `stock_region_code`, defaulting to "US-WEST", records where the pack physically sits, and a candidate replacement pack's region must match the receiving service center's. `refurb_soh_pct` records post-refurbishment state of health: it is required when `pack_type` is `REMANUFACTURED` and must be omitted when `pack_type` is `NEW`. `remanufacture_count`, defaulting to 0, counts completed refurbishment cycles. A pack may optionally be registered as already fitted by supplying `installed_vehicle_id`; the named vehicle must have no pack installed, or the request is refused with `ERR_VEHICLE_ALREADY_HAS_PACK`. Registration also accepts `superseded_pack_id` and `damaged_defective`, though both are normally left for the server to write: `superseded_pack_id` is set on a replacement pack to point at the pack it displaced during a pack replacement, and `damaged_defective` becomes true once a severity `S3` or `S4` thermal event references the pack or a shipment carrying it is rejected.

A pack registered without `installed_vehicle_id` lands in `STOCK`; one registered with it lands in `IN_SERVICE` and the named vehicle's `installed_pack_id` mirror is set to point back. Either way, registration cascade-creates the pack's children: exactly `module_count` **battery modules**, minted with `position_index` running 1 through `module_count` in ascending order, each carrying `pack_id` back to its parent, each starting `HEALTHY` with `cell_delta_mv` at 0, `thermal_runaway_flag` false and `replaced_at` null. Each module's `module_capacity_kwh` is its parent's `nominal_capacity_kwh` divided by its `module_count`, rounded half up to three decimals. Modules are reachable only through their pack's module listing, which returns them in ascending `position_index` order. A module's `status` later reads `DEGRADED` when an assessment names its position among the degraded ones, `FAULTED` when an assessment names it among the faulted ones or a thermal event lists it among the affected ones, and `REPLACED` once a module-replacement fulfilment swaps it out. A pack's two derived roster counters follow from that: `module_replacements_to_date` is the count of its children in `REPLACED`, and `faulted_module_count` is the count of its children in `FAULTED`. Registering a remanufactured pack straight into stock also raises `reman_available_count` on the warranty program and refreshes `reman_stock_state`.

**Service centers** and their technicians complete the master data. A center needs a `name`; `region_code` defaults to "US-WEST", `hv_certification_level` to `L3`, `has_pack_lift` to false, `insulation_tester_cal_due_at` to `2027-01-01T00:00:00Z`, `hv_bay_count` to 2 within an allowed range of 1 to 6, and `labor_rate_cents_per_hour` to 18,333 cents — a warranty reimbursement rate of a little over 183 dollars an hour. A new center is `ACTIVE` with `compliance_score` 100 and all three of `open_hazmat_holds`, `rejected_shipment_count` and `late_notification_count` at zero. A technician is registered against a center, which sets their `service_center_id` from the path; they need a `full_name`, and their `hv_cert_level` defaults to `L3` with `cert_expires_at` defaulting to `2027-06-01T00:00:00Z`. Their `status` is derived rather than stored — `ACTIVE` while `cert_expires_at` remains later than the logical clock, `CERT_LAPSED` from that instant onward — and is re-evaluated on every read. Their `last_hv_window_end_at` starts null.

### 3.2. Telematics Ingestion and the Plausibility Screen

Vehicles report on themselves continuously, and the `TelematicsGateway` is the sole channel through which those reports enter the system. Each ingested **telematics snapshot** hangs off one vehicle and records `captured_at`, the on-vehicle capture instant; `odometer_miles`, which must not be negative; and `reported_capacity_kwh`, the battery management system's own estimate of remaining usable capacity in kilowatt-hours at three decimals. Four further readings are optional and carry defaults: `charge_cycles`, the cumulative count of equivalent full charge cycles, defaulting to 400 and never negative; `max_cell_delta_mv`, the worst-cell voltage spread across the pack in millivolts, defaulting to 40 and never negative; `coolant_temp_c`, the coolant temperature in Celsius at capture, defaulting to 20.0 and — alone among the decimal inputs — carrying no declared scale in section 2.5, so the reading is stored exactly as supplied rather than quantized, which is what lets a value fractionally above a correction boundary land on the far side of it; and `dcfc_session_count`, the cumulative count of DC fast-charge sessions, defaulting to 0 and never negative.

A snapshot is an immutable event. There is no operation to amend one, and the ingest itself never fails on data quality; instead, every row is stored and stamped with a `validity_flag` that records the verdict. The screen runs in a fixed order and the first fault wins. A `captured_at` later than the current logical clock flags the row `INVALID_FUTURE_CAPTURE`. Otherwise, a `reported_capacity_kwh` at or below zero, or one exceeding the installed pack's `nominal_capacity_kwh` multiplied by 1.05 — the five-percent plausibility headroom that allows for benign measurement optimism — flags the row `INVALID_CAPACITY_RANGE`. Otherwise, if some already-`VALID` snapshot on the same vehicle has a `captured_at` at or before this row's `captured_at` and a strictly greater `odometer_miles`, this row is flagged `INVALID_ODOMETER_REGRESSION`, because an odometer cannot run backwards. A row surviving all three reads `VALID`.

Whatever the verdict, the row also receives `corrected_capacity_kwh`, the reported capacity adjusted for temperature. The correction is a step function on `coolant_temp_c` with exact boundaries: below 0.0 degrees the factor is 1.06, from 0.0 up to but not including 15.0 degrees it is 1.03, from 15.0 through 35.0 degrees inclusive it is 1.00, and above 35.0 degrees it is 0.97. A reading of exactly 0.0 therefore takes 1.03, exactly 15.0 takes 1.00, exactly 35.0 still takes 1.00, and anything even fractionally above 35.0 takes 0.97. The corrected figure is the reported capacity multiplied by that factor, rounded half up to three decimals, and it is written for every row including the invalid ones.

Only a `VALID` snapshot moves anything else. When one is accepted, the vehicle's `odometer_miles` is raised to whichever is greater, its existing value or the new row's `odometer_miles`; it is never lowered. The vehicle record is rewritten only when that figure actually changes: a `VALID` row that does not beat the stored maximum, like every invalid row, leaves the vehicle's `updated_at` and `version` exactly where they stood — so only an ingest that really moves the odometer stales a held `expected_vehicle_version`. Invalid rows are stored and are readable — a vehicle's snapshot list may be filtered by `validity_flag` — but they never contribute to an odometer read, a cell-delta read, or any capacity estimate.

### 3.3. Diagnosing Capacity Retention: the State-of-Health Assessment

A claim cannot exist without a diagnostic behind it, and the **state-of-health assessment** is that diagnostic. A `ServiceTechnician` produces one by naming the `vehicle_id`, the `pack_id` of the pack currently in that vehicle, the `technician_id` of the technician signing the diagnostic, and the `variant` to run. The named pack must be the vehicle's `installed_pack_id`; naming any other pack is refused with `ERR_PACK_VEHICLE_MISMATCH`. The payload also carries `expected_vehicle_version`, because a new assessment supersedes the vehicle's earlier ones and must therefore be written against a vehicle view the client has actually seen.

Two variants exist and they answer the same question differently. `TELEMATICS_FLEET` derives capacity from the vehicle's own recent telemetry. `BENCH_CAPACITY_TEST` uses a capacity the technician measured on a bench, supplied as `bench_measured_capacity_kwh`; that field is required for the bench variant and must be absent for the fleet variant, and either mistake is refused with `ERR_BENCH_CAPACITY_REQUIRED`.

Either variant may also declare module condition. `module_fault_positions` lists the integer `position_index` values this diagnostic declares faulted; `module_degraded_positions` lists those it declares merely degraded. Both arrays are accepted for both variants, both default to empty, and both are written through to the pack's modules — setting those children to `FAULTED` and `DEGRADED` respectively — *before* any retention arithmetic runs. Every entry in either array must be an integer between 1 and the pack's `module_count`, neither array may repeat a position, and the two arrays must be disjoint; any violation is refused with `ERR_MODULE_POSITION_INVALID`. Because the write happens first, the pack's `faulted_module_count` is re-derived before it is read by the arithmetic that follows.

The **diagnostic gate** then runs, in a pinned order where the first rule to fire wins and short-circuits the rest, and its verdict lands in `diagnostic_validity`. Start from the set of every snapshot on this vehicle whose `validity_flag` reads `VALID`; rows with any other flag are excluded from every set that follows and never contribute an odometer or cell-delta reading. First, if that set is empty, the verdict is `INSUFFICIENT_DATA`. Otherwise narrow to the fresh subset — those whose `captured_at` falls at or after the logical clock less `snapshot_freshness_days` days, with the lower bound inclusive so a snapshot captured exactly on the boundary instant still counts as fresh. Second, if the fresh subset is empty, the verdict is `STALE_TELEMETRY`: the vehicle has reported at some point, but not recently enough. Otherwise build the **window** by ordering the fresh subset newest `captured_at` first, breaking ties by newest `created_at` first, and taking at most `snapshot_window_size` rows. The window's size is recorded as `window_snapshot_count`, and the newest row in it supplies both `assessed_odometer_miles` and the assessment's own `max_cell_delta_mv`; both read 0 when the window is empty. Third, for the `TELEMATICS_FLEET` variant only, a window holding fewer rows than `snapshot_min_count` yields `INSUFFICIENT_DATA`. Fourth, for the `BENCH_CAPACITY_TEST` variant only, a `bench_measured_capacity_kwh` greater than the variant's own denominator multiplied by 1.05 yields `BENCH_OUT_OF_RANGE`. Surviving all four, the verdict is `VALID`.

The retention ratio itself is capacity over a nominal basis, expressed as a percentage: `retention_pct` is `estimated_capacity_kwh` divided by `nominal_basis_kwh`, multiplied by one hundred, rounded half up to two decimals. Both `estimated_capacity_kwh` and `retention_pct` are null whenever `diagnostic_validity` is anything other than `VALID`, and they are the only fields a non-`VALID` verdict nulls: `window_snapshot_count`, `nominal_basis_kwh`, `assessed_odometer_miles`, `max_cell_delta_mv`, `elapsed_months`, `coverage_position` and `applicable_min_retention_pct` are each written on exactly the rules given below whatever the verdict, so an `INSUFFICIENT_DATA`, `STALE_TELEMETRY` or `BENCH_OUT_OF_RANGE` assessment still publishes its coverage position and, unless that position reads `OUT_OF_COVERAGE`, a non-null `applicable_min_retention_pct`. What differs between the variants is both the numerator and the denominator, and the divergence is deliberate.

For `TELEMATICS_FLEET`, the denominator `nominal_basis_kwh` is the pack's full beginning-of-life `nominal_capacity_kwh`; faulted modules are *not* excluded from it. The numerator is a trimmed mean of the window's `corrected_capacity_kwh` values. When the window holds exactly `snapshot_window_size` rows, the values are sorted ascending, the single lowest and the single highest are dropped, and the remainder are averaged; sorting ties need no tie-break, since the mean of a multiset does not depend on order. When the window is smaller than that — three or four rows — no trimming happens and all of the values are averaged. Either way the resulting mean is rounded half up to three decimals to give `estimated_capacity_kwh`.

For `BENCH_CAPACITY_TEST`, the numerator is simply `bench_measured_capacity_kwh`, and the denominator is derated pro rata for faulted modules. Count the pack's children in `FAULTED` *after* this assessment's `module_fault_positions` have been written, then take the pack's `nominal_capacity_kwh`, multiply it by the module count less that faulted count, divide by the module count, and round half up to three decimals. The consequence is that for one and the same measured capacity the two variants return different retention figures whenever any module is faulted, because only the bench variant shrinks the denominator. Both are defensible readings of capacity retention; these requirements pin which reading each variant uses.

Alongside retention, the assessment fixes the vehicle's position on the coverage map. `elapsed_months` is the whole number of months from the vehicle's `in_service_date` to the current logical clock, floored on the day of month: take the calendar year and month difference in UTC, multiply the year difference by twelve, add the month difference, and subtract one if the current day of month is earlier than the in-service day of month. Tier selection then scans `retention_schedule` in its stored ascending order and takes the *first* row where both axes fall inside the row — `elapsed_months` at or below that row's `through_months` and `assessed_odometer_miles` at or below that row's `through_miles`. Both bounds are inclusive. When a row is selected, `coverage_position` reads `IN_COVERAGE` and `applicable_min_retention_pct` takes that row's `min_retention_pct`. When no row matches, the goodwill test runs: if `elapsed_months` is at or below `coverage_months` plus `goodwill_months` *and* `assessed_odometer_miles` is at or below `coverage_miles` plus `goodwill_miles` — both axes must be inside the band — then `coverage_position` reads `GOODWILL_BAND` and `applicable_min_retention_pct` takes the `min_retention_pct` of the schedule's last row. Failing that, `coverage_position` reads `OUT_OF_COVERAGE` and `applicable_min_retention_pct` is null. Note carefully which mileage figure feeds this: it is `assessed_odometer_miles` from the fresh window, not the vehicle's lifetime `odometer_miles` maximum, which may have come from a snapshot that has since aged out of the freshness window.

From those pieces the assessment publishes a single summary boolean. `qualifies_for_claim` is true when `diagnostic_validity` is `VALID`, `coverage_position` is either `IN_COVERAGE` or `GOODWILL_BAND`, and `retention_pct` is at or below `applicable_min_retention_pct` — retention exactly at the threshold qualifies.

Finally, writing an assessment closes the book on the vehicle's earlier ones: every prior assessment on the same `vehicle_id` has `superseded` set to true, and a superseded assessment can no longer back a claim. The vehicle's `version` increments by one as part of the same operation, which is precisely why the next writer's `expected_vehicle_version` must be refreshed. Assessments can be listed and filtered by `vehicle_id`, `pack_id`, `technician_id`, `variant`, `diagnostic_validity` and `superseded`.

### 3.4. Filing a Claim and the Remedy Recommendation Ladder

With a qualifying diagnostic in hand, a `ServiceTechnician` files a **warranty claim**. The payload names four things: the `vehicle_id`, the `service_center_id` of the center that will act as the center of record for both diagnosis and fulfilment, the `assessment_id` of the backing diagnostic, and the `diagnosing_technician_id` of the technician standing behind it. The acting `X-User-ID` must equal that `diagnosing_technician_id`, and that technician must belong to the named center — a mismatch is refused with `ERR_TECHNICIAN_CENTER_MISMATCH` — and must not be `CERT_LAPSED`. The backing assessment must describe the same vehicle as the claim, or the filing is refused with `ERR_ASSESSMENT_VEHICLE_MISMATCH`.

Filing is guarded by a dense set of eligibility checks, and the order among them is the global order given in Section 2.7. Practically, the assessment-integrity checks come first: an assessment whose `superseded` flag is true is refused with `ERR_ASSESSMENT_SUPERSEDED`; one already cited by another claim that is not `CLOSED` is refused with `ERR_ASSESSMENT_ALREADY_CLAIMED`; and one whose `diagnostic_validity` is `STALE_TELEMETRY`, `INSUFFICIENT_DATA` or `BENCH_OUT_OF_RANGE` is refused with `ERR_DIAGNOSTIC_NOT_VALID`. That third check runs before any coverage or retention comparison for a concrete reason: on an invalid assessment the retention and coverage fields are null, so comparing them would be meaningless. Only afterwards do the substantive constraints run — a vehicle that already carries a claim in any status other than `CLOSED` is refused with `ERR_CLAIM_ALREADY_OPEN`, an assessment whose `retention_pct` is strictly above its `applicable_min_retention_pct` is refused with `ERR_RETENTION_ABOVE_THRESHOLD` (retention exactly at the threshold qualifies), and an assessment whose `coverage_position` reads `OUT_OF_COVERAGE` is refused with `ERR_OUT_OF_COVERAGE`. Two further preconditions are enforced as conflicts (HTTP 409) without a dedicated identifier: a claim may not be filed while the vehicle's `warranty_hold` is true or while any thermal event on that vehicle still has `event_status` `OPEN`, and it may not be filed at a center whose `status` is `DECERTIFIED`.

A successful filing lands the claim in `SUBMITTED`, sets `info_request_round` and `reopened_count` to zero, and derives `fulfilment_blocked` from the center of record's current status — false at an `ACTIVE` center, true at one that is `SHIPPING_SUSPENDED` or `DECERTIFIED`.

Filing also computes the claim's `recommended_remedy` and the `recommendation_basis` that explains it, and this ladder is the analytical heart of the program. Seven quantities feed it, all read fresh at this instant rather than from any cache: the pack's `faulted_module_count`, the pack's `module_count`, the backing assessment's `max_cell_delta_mv` and `retention_pct`, the pack's `module_replacements_to_date`, the program's `module_replacement_cap`, and the number of thermal events on this pack whose `severity` is `S3` or `S4` — counted regardless of their containment progress. The rungs are evaluated in a pinned order and the first that fires wins:

1. If the pack has ever had at least one `S3` or `S4` thermal event, the recommendation is `PACK_REPLACEMENT` with basis `THERMAL_HISTORY`. A pack that has been through thermal runaway is never module-repaired.
2. Otherwise, if the assessment's `max_cell_delta_mv` is at or above the program's `cell_delta_pack_threshold_mv`, the recommendation is `PACK_REPLACEMENT` with basis `CELL_DELTA`.
3. Otherwise, if the assessment's `retention_pct` is strictly below the program's `pack_replacement_retention_pct`, the recommendation is `PACK_REPLACEMENT` with basis `RETENTION_FLOOR`. A pack that has degraded past the floor is beyond economical module repair.
4. Otherwise, two ceilings on module repair are computed and the tighter of the two governs. The remaining lifetime allowance is the program's `module_replacement_cap` less the pack's `module_replacements_to_date`, floored at zero. The structural ceiling is one quarter of the pack's `module_count`, rounded down to a whole number of modules. If the pack's `faulted_module_count` is strictly greater than the smaller of those two ceilings, the recommendation is `PACK_REPLACEMENT` with basis `MODULE_ALLOWANCE`.
5. Otherwise, if the pack has at least one faulted module, the recommendation is `MODULE_REPLACEMENT` with basis `MODULE_FAULT`.
6. Otherwise nothing physical is wrong with the modules at all, and the recommendation is `SOFTWARE_REMEDIATION` with basis `NO_MODULE_FAULT`.

An adjudicator who wants more evidence before deciding can send the claim back. Opening an information request moves the claim from `SUBMITTED` to `INFO_REQUESTED`, optionally recording a `reason_note`, and increments `info_request_round` by one. The program's `info_request_limit` caps this: a request opened when `info_request_round` has already reached the limit is refused with `ERR_INFO_REQUEST_LIMIT_EXCEEDED`. The technician answers by resubmitting, which returns the claim from `INFO_REQUESTED` to `SUBMITTED` and may carry a free-text `note` plus a replacement `assessment_id`. When a new `assessment_id` is supplied it must name an assessment on the same vehicle whose `superseded` flag is false, whose `diagnostic_validity` is `VALID` and whose `qualifies_for_claim` is true; the claim is repointed at it and both `recommended_remedy` and `recommendation_basis` are recomputed from current pack, thermal and assessment state, with `coverage_position` re-read from the possibly-new assessment. Only the technician recorded as the claim's `diagnosing_technician_id` may resubmit. Crucially, the return to `SUBMITTED` does *not* reset `info_request_round`, so with the default limit of two the adjudicator's third information request on the same claim is refused.

### 3.5. Adjudication: Choosing the Remedy, Reserving the Pack, Pricing the Settlement

A `WarrantyAdjudicator` decides a `SUBMITTED` claim by naming an `approved_remedy`. Three optional companions may travel with it: `replacement_pack_id` to nominate a specific replacement pack rather than letting the selector choose, `linked_campaign_id` to name the software campaign a software remedy will run under, `override_justification` to justify departing from the system's own recommendation, and `decision_note` for the adjudicator's free-text record. Whichever branch is taken, the decision writes the acting `X-User-ID` into `adjudicated_by_user_id`, and that value is what the dispute two-person rule later compares against.

Departing from the recommendation is permitted but bounded. When `approved_remedy` differs from the claim's `recommended_remedy`, an `override_justification` must be present. On top of that there is a safety lock: remedies have an ordinal strength, with `SOFTWARE_REMEDIATION` weaker than `MODULE_REPLACEMENT`, which is weaker than `PACK_REPLACEMENT`, and an adjudicator may not approve anything weaker than a `PACK_REPLACEMENT` recommendation whose `recommendation_basis` is `THERMAL_HISTORY` or `CELL_DELTA`. Attempting to is refused with `ERR_REMEDY_OVERRIDE_FORBIDDEN`. Denial is always available, whatever the recommendation said. A `THERMAL_HISTORY` recommendation in particular can never be collapsed to a module approval: the module branch below refuses outright when the recommendation basis is `THERMAL_HISTORY`, regardless of any justification offered.

The four branches move the claim to four different states, and each carries its own preconditions and its own consequences.

**Approving a module replacement** moves the claim from `SUBMITTED` to `APPROVED_MODULE`. It requires that the claim be `SUBMITTED`; that `approved_remedy` match `recommended_remedy` or an `override_justification` be present; that the claim's `recommendation_basis` not be `THERMAL_HISTORY`; that the center of record's `hv_certification_level` be `L2` or `L3`; and that the program's liability ceiling still accommodate the computed exposure. On success the settlement fields are computed as described below, the resulting `oem_total_cents` is added to the program's `accrued_liability_cents`, and `adjudicated_by_user_id` is stamped.

**Approving a pack replacement** moves the claim from `SUBMITTED` to `APPROVED_PACK`. It requires that the claim be `SUBMITTED`; that `approved_remedy` match `recommended_remedy` or an `override_justification` be present; that the center of record's `hv_certification_level` be exactly `L3` and its `has_pack_lift` be true; that a replacement pack be available; and that the liability ceiling accommodate the exposure. On success four things happen in sequence: the replacement pack is chosen and written to the claim's `replacement_pack_id`; that pack moves from `STOCK` to `RESERVED`; because the pack left `STOCK`, the program's `reman_available_count` falls by one — but only when the selected pack's `pack_type` is `REMANUFACTURED`; and because `reman_available_count` may now be zero, `reman_stock_state` is refreshed to `DEPLETED`. The settlement is then computed, `oem_total_cents` is added to `accrued_liability_cents`, and `adjudicated_by_user_id` is stamped.

**Approving a software remediation** moves the claim from `SUBMITTED` to `APPROVED_SOFTWARE`. It requires that the claim be `SUBMITTED`; that a `linked_campaign_id` be present and name a campaign whose `status` is `LIMITED_RELEASE` or `FIELD_RELEASE`; that the campaign's `applies_to_model_code` equal the vehicle's `model_code`; and that `approved_remedy` match `recommended_remedy` or an `override_justification` be present. On success the campaign is recorded on the claim's `linked_campaign_id`. If no remediation consent yet exists for that campaign-and-vehicle pair, one is created with `consent_status` `PENDING` and `solicitation_round` 1, and the campaign's `solicited_consent_count` and `open_consent_count` each rise by one. The settlement is computed with a zero parts line, its `oem_total_cents` is added to `accrued_liability_cents`, and `adjudicated_by_user_id` is stamped.

**Denying the claim** moves it from `SUBMITTED` to `DENIED` and requires an `override_justification` to be present, because a denial is by definition a departure from a remedy recommendation. It records the decision verbatim, so `approved_remedy` reads `DENIED`; it sets `denial_reason` to `ADJUDICATOR_DECISION` and zeroes the money: `remedy_cost_cents`, `owner_share_cents`, `oem_share_cents`, `admin_fee_cents` and `oem_total_cents` all read 0, `proration_factor` reads 0.0000, and the program's `accrued_liability_cents` is left entirely unchanged. No cost estimate and no settlement waterfall run at all on a denial. `adjudicated_by_user_id` is stamped exactly as on an approval.

#### Choosing the replacement pack

When a pack approval arrives without an explicit `replacement_pack_id`, the selector runs. Its eligibility predicate is evaluated against the pack being removed and the claim's service center, and every clause must hold: the candidate's `pack_type` is `REMANUFACTURED`; its `status` is `STOCK`; its `installed_vehicle_id` is null; its `stock_region_code` equals the center's `region_code`; its `module_count` equals the removed pack's `module_count`; its `nominal_capacity_kwh` is at least the removed pack's `nominal_capacity_kwh`; and its `refurb_soh_pct` is at or above the program's `reman_min_soh_pct`, with the boundary value accepted. Only packs in `STOCK` are candidates at all — packs in `RESERVED`, `IN_SERVICE`, `REMOVED`, `QUARANTINED` or `SCRAPPED` are invisible to the selector even when every other clause holds.

Surviving candidates are ranked by `refurb_soh_pct` descending, then by `remanufacture_count` ascending, then by `created_at` ascending, and the first row is taken. Because `created_at` is the final key the order is total and ties are impossible.

If the remanufactured pool is empty, the program's `allow_new_pack_substitution` decides what happens. When it is false, the adjudication is refused with `ERR_NO_REMAN_PACK_AVAILABLE`. When it is true, the selector re-runs over packs whose `pack_type` is `NEW`, dropping the `refurb_soh_pct` clause entirely — a new pack has no `refurb_soh_pct` and it is *not* treated as 100.00 for ranking purposes, the key is simply skipped — and ranking the survivors by `remanufacture_count` ascending, then `created_at` ascending. If that pool is also empty the adjudication is refused with `ERR_NO_REMAN_PACK_AVAILABLE` as well. Selecting a `NEW` pack still moves it from `STOCK` to `RESERVED`, but leaves `reman_available_count` untouched, since that mirror counts remanufactured stock only.

An adjudicator who names `replacement_pack_id` explicitly bypasses the selector but not the checks. The named pack's `stock_region_code` must equal the claim's center's `region_code` and its `module_count` must equal the removed pack's `module_count`, or the request is refused with `ERR_PACK_REGION_MISMATCH`. Its `status` must be `STOCK` with a null `installed_vehicle_id`, and if its `pack_type` is `REMANUFACTURED` its `refurb_soh_pct` must be at or above the program's `reman_min_soh_pct`; otherwise the request is refused with `ERR_PACK_NOT_IN_STOCK`.

#### Costing the remedy

The remedy cost is four line items, each rounded to whole cents on its own before the four are added. Let the faulted module count be the pack's `faulted_module_count` as it stands at adjudication time.

The **parts line** is the program's `module_unit_price_cents` multiplied by the faulted module count for a module replacement; for a pack replacement it is the program's `pack_price_reman_cents` when the selected replacement pack's `pack_type` is `REMANUFACTURED` and its `pack_price_new_cents` when that pack is `NEW`; and for a software remediation it is zero. This line is an exact integer and needs no rounding.

The **labour line** is a number of hours multiplied by the center's `labor_rate_cents_per_hour`, rounded half up to whole cents. The hours are the program's `labor_hours_module` for a module replacement, its `labor_hours_pack` for a pack replacement, and a fixed half an hour for a software remediation.

The **hazmat line** prices the outbound freight the remedy generates. For a software remediation there is no freight at all: the surcharge basis is zero and the shipped weight is 0.000 kilograms, so the line is zero. Otherwise the basis is chosen in a pinned order — the program's `surcharge_un3536_cents` whenever the pack is flagged `damaged_defective`, and only failing that the `surcharge_un3480_cents` for a pack replacement or the `surcharge_un3481_cents` for a module replacement. The shipped weight is the pack's whole `gross_weight_kg` for a pack replacement, and for a module replacement it is the pack's `gross_weight_kg` scaled by the faulted module count over the pack's `module_count`, rounded half up to three decimals. The line is then the basis multiplied by the shipped weight and divided by one hundred — the surcharges are quoted per 100 kilograms — rounded half up to whole cents.

The **diagnostic line** is the program's `diagnostic_fee_cents`, an exact integer.

`remedy_cost_cents` is the sum of those four rounded lines. Summing the raw products and rounding once at the end is not equivalent and is not permitted.

#### Splitting the cost and stamping the ledger

The settlement waterfall then runs in a pinned order. It looks circular at first glance — `admin_fee_cents` keys off `oem_share_cents`, which depends on `owner_share_cents`, which depends on `remedy_cost_cents`, whose hazmat line in turn depends on the pack's `damaged_defective` flag — but it is not: `admin_fee_cents` never re-enters `remedy_cost_cents`, `proration_factor` or `owner_share_cents`.

First, `settlement_variant` is fixed from the backing assessment's coverage position: `FULL_COVERAGE` when `coverage_position` is `IN_COVERAGE`, and `GOODWILL_PRORATED` when it is `GOODWILL_BAND`. Second, `remedy_cost_cents` is computed as above. Third, `proration_factor` is determined. Under `FULL_COVERAGE` it is forced to 0.0000. Under `GOODWILL_PRORATED` it measures how far into the goodwill band the vehicle has travelled on its worse axis: take the months overrun, which is the assessment's `elapsed_months` less the program's `coverage_months` floored at zero, and the miles overrun, which is the assessment's `assessed_odometer_miles` less the program's `coverage_miles` floored at zero; divide the months overrun by `goodwill_months` and the miles overrun by `goodwill_miles`; take the larger of the two fractions; cap it at 1.0; and round half up to four decimals.

Fourth, `owner_share_cents` is `remedy_cost_cents` multiplied by `proration_factor`, rounded half up to whole cents. Fifth, `oem_share_cents` is `remedy_cost_cents` less `owner_share_cents`. Sixth, `admin_fee_cents` is a tiered administration charge keyed on `oem_share_cents`, with each tier's lower bound inclusive: an OEM share below 200,000 cents attracts no administration fee at all, a share from 200,000 up to but not including 500,000 cents attracts 7,500 cents, and a share of 500,000 cents or more attracts 15,000 cents. Seventh, `oem_total_cents` is `oem_share_cents` plus `admin_fee_cents`. Eighth, that total is added to the program's `accrued_liability_cents`.

The two settlement variants therefore diverge by more than the proration delta. Under `FULL_COVERAGE` the owner pays nothing, the OEM share equals the whole remedy cost, and the administration tier is evaluated against that full figure. Under `GOODWILL_PRORATED` the owner share is positive and the OEM share shrinks — which can drop it into a *lower* administration tier than the same remedy cost would have hit under full coverage. Identical remedy costs consequently yield different `oem_total_cents` figures under the two variants.

The fiscal ceiling is checked last, after every safety, referential and constraint check has passed, so that no money rule can mask a safety failure. If the program's current `accrued_liability_cents` plus this claim's computed `oem_total_cents` would exceed the program's `liability_cap_cents`, the adjudication is refused with `ERR_LIABILITY_CAP_EXCEEDED`; landing exactly on the cap is permitted.

### 3.6. Executing the Remedy: Bay Windows, Technician Cooldown and Closure

A `ServiceTechnician` executes an approved hardware remedy by booking a high-voltage bay window. The request carries exactly three fields — `fulfilment_technician_id`, `hv_bay_window_start` and `hv_bay_window_end` — and the acting `X-User-ID` must equal `fulfilment_technician_id`. The claim moves from `APPROVED_MODULE` or `APPROVED_PACK` to `FULFILLED`. A claim in any other state is refused with `ERR_CLAIM_NOT_FULFILLABLE`, except that a `CLOSED` claim is refused earlier still with `ERR_CLAIM_TERMINAL`, which guards every operation on a claim. A claim whose `fulfilment_blocked` flag is true cannot be fulfilled at all; that flag is derived from the center of record's standing, is set when a shipment rejection suspends the center, and is cleared when the center returns to `ACTIVE`.

The gauntlet of safety checks runs in a fixed order, and each has its own identifier so an implementation cannot collapse them.

First the center of record must have `status` `ACTIVE`; a center in `SHIPPING_SUSPENDED` or `DECERTIFIED` is refused with `ERR_CENTER_NOT_CERTIFIED`. Next the center's `hv_certification_level` must reach the remedy's tier — exactly `L3` for a pack replacement, `L2` or `L3` for a module replacement, any level for a software remediation — or the request is refused with `ERR_CENTER_CERT_LEVEL_INSUFFICIENT`. A pack replacement additionally requires the center's `has_pack_lift` to be true, or `ERR_PACK_LIFT_REQUIRED`. For either hardware remedy the center's `insulation_tester_cal_due_at` must be strictly later than the current logical clock, or `ERR_INSULATION_TESTER_OVERDUE`; a calibration falling due exactly at the current instant is overdue and rejects.

Then the technician is examined. The named technician's `cert_expires_at` must be strictly later than the current logical clock — equivalently, the technician's derived `status` must be `ACTIVE` and not `CERT_LAPSED` — or the request is refused with `ERR_TECHNICIAN_CERT_EXPIRED`. The technician's own `hv_cert_level` must reach the remedy's tier, exactly `L3` for a pack replacement and `L2` or `L3` for a module replacement, or `ERR_TECHNICIAN_LEVEL_INSUFFICIENT`. Note that the center tier and the technician tier are checked separately and both must hold: an `L3` technician at an `L2` center cannot perform a pack replacement, and neither can an `L2` technician at an `L3` center. The technician's `service_center_id` must also equal the claim's `service_center_id`, which is enforced earlier by `ERR_TECHNICIAN_CENTER_MISMATCH`.

A safety interlock then blocks fulfilment while a serious thermal condition is still open: if any thermal event on the claim's pack has `severity` `S3` or `S4` and a `containment_status` other than `CONTAINMENT_CLOSED`, the request is refused with `ERR_THERMAL_CONTAINMENT_OPEN`. Events of severity `S1` or `S2` do not block fulfilment however far through containment they are.

Only after all of that do the scheduling checks run. `hv_bay_window_end` must be strictly later than `hv_bay_window_start`, or the request is refused with `ERR_INVALID_BAY_WINDOW` — a zero-length window is invalid. Bay occupancy is then evaluated as a half-open interval running from `hv_bay_window_start` up to but not including `hv_bay_window_end`. Count the claims at the same center whose `adjudication_status` is `FULFILLED` or `CLOSED` and whose own half-open window overlaps the requested one; if that count is not strictly less than the center's `hv_bay_count`, the request is refused with `ERR_HV_BAY_CAPACITY_EXCEEDED`. Because the interval is half-open, a window that begins exactly when another ends does not overlap it, and two back-to-back bookings are always admissible however many bays the center has. Because the check is an aggregate rather than a pairwise exclusion, a center with two bays admits a second concurrent booking and refuses only the third. Claims in `APPROVED_MODULE`, `APPROVED_PACK`, `APPROVED_SOFTWARE`, `SUBMITTED`, `INFO_REQUESTED` or `DENIED` occupy no bay even if they carry window fields.

Finally the technician cooldown is checked. The requested `hv_bay_window_start` must be at or later than the technician's `last_hv_window_end_at` plus sixty minutes, or the request is refused with `ERR_TECHNICIAN_COOLDOWN_CONFLICT`. The lower bound is closed: a start exactly sixty minutes after the previous window's end is accepted, while fifty-nine minutes is refused. A technician whose `last_hv_window_end_at` is null has never worked a bay and is subject to no cooldown at all. The cooldown is per technician and independent of the bay-capacity check, so a center with free bays can still be unable to schedule a particular technician.

On success the claim records `fulfilment_technician_id`, `hv_bay_window_start` and `hv_bay_window_end`, and sets `pack_shipment_required` to true for either hardware remedy. The technician's `last_hv_window_end_at` is raised to the later of its current value and the submitted `hv_bay_window_end`, so booking an earlier window after a later one never shortens the cooldown that the later booking established.

The hardware consequences differ by remedy. A **module replacement** moves every module of the pack whose `status` is `FAULTED` to `REPLACED` and stamps each one's `replaced_at` with the current logical clock; because those rows changed status, the pack's `module_replacements_to_date` rises by the number of modules just replaced and its `faulted_module_count` is re-derived, which leaves it at zero. Modules in `DEGRADED` are untouched by fulfilment. A **pack replacement** moves the vehicle's currently installed pack from `IN_SERVICE` — or from `QUARANTINED`, if a thermal event had quarantined it — to `REMOVED` and nulls its `installed_vehicle_id`; moves the reserved replacement pack from `RESERVED` to `IN_SERVICE`, sets its `installed_vehicle_id` to the claim's `vehicle_id` and its `superseded_pack_id` to the removed pack's identifier; and updates the vehicle so that `installed_pack_id` points at the replacement, `warranty_hold` becomes false and `status` returns to `ACTIVE`. The pack approval's fulfilment additionally requires that the pack named by `replacement_pack_id` still hold `status` `RESERVED`. Removing a pack that stands in `QUARANTINED` rather than `IN_SERVICE` carries one extra requirement: every thermal event referencing that pack, of any `severity`, must have reached `containment_status` `CONTAINMENT_CLOSED`. The removed pack's `damaged_defective` flag stays true through the removal, so its outbound shipment will classify as `UN3536`.

A **software remediation** is not fulfilled through the bay-window path at all. It reaches `FULFILLED` by system action when its linked remediation consent reaches `APPLIED`, and that transition sets `pack_shipment_required` to false, since no pack was removed. At most one such claim can exist per vehicle, because a vehicle may hold only one non-terminal claim at a time.

Closure is the adjudicator's act, carries only an optional `closure_note`, and is terminal. A claim may be closed only from `FULFILLED` or `DENIED`; anything else is refused with `ERR_CLAIM_NOT_CLOSABLE`. Closing from `FULFILLED` additionally requires either that `pack_shipment_required` be false or that a pack shipment for the removed pack — for a module remedy, the pack the modules came out of — have reached `status` `RECEIVED`. Closure freezes the settlement fields exactly as they stand and leaves the program's `accrued_liability_cents` untouched, so the accrual booked at adjudication persists through closure. Closing from `DENIED` requires that no capacity dispute on the claim still be in `LAB_ASSIGNED` or `LAB_RESULT_RECEIVED`; closing a denial ends the dispute window, because the claim then leaves the disputable set and any later dispute filing is refused with `ERR_CLAIM_NOT_DISPUTABLE`.

### 3.7. Thermal Events: Two Independent Dimensions

A thermal event is reported either by the telematics gateway or by a technician at a center, and it is the only entity in this system that tracks two independent lifecycles at once. Containment is what the workshop does to the pack; notification is what the manufacturer owes the regulator. Neither dimension waits on the other, and a single derived field joins them.

Reporting an event supplies `vehicle_id`, `pack_id`, `severity` (`S1` for a thermal warning through `S4` for thermal runaway with venting), `detected_at`, `source` (`TELEMATICS` for gateway-detected events, `SERVICE_CENTER` for technician-reported ones) and an optional `affected_module_positions`, an array of integer `position_index` values that defaults to empty. The submitted `pack_id` must equal the vehicle's `installed_pack_id`, or the report is refused with `ERR_PACK_VEHICLE_MISMATCH`. The `detected_at` instant must be at or before the current logical clock, or the report is refused with `ERR_DETECTED_AT_IN_FUTURE`; an instant exactly equal to the clock is accepted. A vehicle may carry only one event whose `event_status` is `OPEN`; reporting a second while the first is open is a conflict (HTTP 409) without a dedicated identifier.

Creation sets `containment_status` to `DETECTED`, `containment_steps_completed` to 0 and `event_status` to `OPEN`, and it fixes the notification obligation immediately. The deadline hangs off `detected_at`, not `created_at`: an event detected in the field and reported to the API hours later has already consumed part of its window. For `S4` the `notification_deadline_at` is `detected_at` plus twenty-four hours; for `S3` it is `detected_at` plus seventy-two hours; and for `S1` or `S2` there is no deadline at all, so `notification_deadline_at` stays null. Correspondingly `notification_status` starts at `PENDING` when a deadline exists and at `NOT_REQUIRED` when it does not. `notification_filed_at`, `regulator_reference` and `reporting_service_center_id` all start null.

An `S3` or `S4` report also fires the safety cascade described in section 2.8: the pack's `damaged_defective` becomes true, its `hazmat_classification` becomes `UN3536`, and its `status` moves from `IN_SERVICE` to `QUARANTINED`; every module of that pack whose `position_index` appears in `affected_module_positions` has `thermal_runaway_flag` set to true and `status` moved to `FAULTED`; the vehicle's `warranty_hold` becomes true and its `status` moves to `IMMOBILIZED`; every remediation consent on that vehicle in `PENDING` or `GRANTED` moves to `EXPIRED`; and each affected campaign recomputes `open_consent_count` and auto-closes if that reaches zero while it is in `LIMITED_RELEASE` or `FIELD_RELEASE`. For `S4` only, and evaluated *before* the consent-expiry step, every campaign whose `target_defect` is `THERMAL_MANAGEMENT`, whose `applies_to_model_code` equals the vehicle's `model_code` and whose `status` is `LIMITED_RELEASE` or `FIELD_RELEASE` moves to `SUSPENDED` — and because a suspended campaign never auto-closes, that ordering is what keeps a thermally suspect campaign from being silently retired. An `S1` or `S2` report fires none of this: the pack stays `IN_SERVICE`, the vehicle stays `ACTIVE`, consents are untouched, and `affected_module_positions` records the implicated positions without changing any module's status or flag.

#### Working the containment dimension

Containment advances one step at a time and only forward. Each call carries `step_index` and an optional `step_note`, and the submitted `step_index` must be exactly `containment_steps_completed` plus one; anything else — a skipped step, a repeated step, or a step out of order — is refused with `ERR_CONTAINMENT_STEP_OUT_OF_ORDER`. Every accepted step raises `containment_steps_completed` by one.

Step 1 isolates the high-voltage system and moves `containment_status` from `DETECTED` to `ISOLATED`. It requires the acting technician's `hv_cert_level` to be `L2` or `L3` and the technician's `status` to be `ACTIVE`.

Step 2 quarantines the pack and moves `containment_status` from `ISOLATED` to `PACK_QUARANTINED`. It requires the pack's `status` to be `QUARANTINED` — which an `S3` or `S4` event has already arranged at creation. For an `S1` or `S2` event the step itself performs the quarantine: the pack moves from `IN_SERVICE` to `QUARANTINED` and its `damaged_defective` becomes true. So the same step is a no-op on the pack for a severe event and the quarantining act for a mild one. When the pack has an origin center of record, that center's `open_hazmat_holds` rises by one at this step.

Step 3 closes containment and moves `containment_status` from `PACK_QUARANTINED` to `CONTAINMENT_CLOSED`. Beyond the ordering requirement it demands that the regulatory dimension already be settled: `notification_status` must be `NOT_REQUIRED`, `FILED` or `LATE_FILED`. Attempting to close containment while `notification_status` is still `PENDING` is refused with `ERR_NOTIFICATION_STILL_PENDING`, because the containment dimension may not close while the regulatory dimension is unsettled. This is the single point at which the two dimensions touch, and it is one-way: notification never waits on containment.

#### Working the notification dimension

A `RegulatoryLiaison` files the notification, supplying `reporting_service_center_id` and `regulator_reference`, both required. `notification_status` must be `PENDING`, or the filing is refused with `ERR_NOTIFICATION_ALREADY_FILED` — which is also what a second filing attempt receives, and what a filing against an `S1` or `S2` event whose status is `NOT_REQUIRED` receives, since that status is terminal on this dimension. This dimension advances independently of containment: `containment_status` may be `DETECTED`, `ISOLATED` or `PACK_QUARANTINED` at filing time and the filing is unaffected.

The filing stamps `notification_filed_at` with the current logical clock and records `regulator_reference` and `reporting_service_center_id`. Timeliness is then decided by a strict comparison: if the current logical clock is *strictly after* `notification_deadline_at` the filing is late; filing at the exact deadline instant is on time. An on-time filing sets `notification_status` to `FILED` and has no compliance consequence whatsoever.

A late filing sets `notification_status` to `LATE_FILED` and damages exactly one center: the one named by `reporting_service_center_id`, whose `late_notification_count` rises by one. That center's `compliance_score` is then recomputed from scratch as one hundred less fifteen for each rejected shipment less forty for each late notification, floored at zero, and if and only if the recomputed score is at or below twenty the center's `status` moves to `DECERTIFIED`, at which point every claim at that center whose `adjudication_status` is not `DENIED` or `CLOSED` has `fulfilment_blocked` set to true. A single late filing at a center with no rejected shipments yields a score of sixty and does not decertify. No other center is touched — not the pack's origin center, not the center handling containment, only the reporting center.

Both dimensions feed the derived join. `event_status` reads `COMPLETE` when `containment_status` is `CONTAINMENT_CLOSED` *and* `notification_status` is `NOT_REQUIRED`, `FILED` or `LATE_FILED`, and `OPEN` in every other case. It is re-derived after every containment step and after every filing. Because a claim cannot be filed for a vehicle with an `OPEN` event, and because containment cannot close until notification settles, an unreported `S4` event freezes the vehicle's warranty activity entirely.

### 3.8. Software Remediation Campaigns and Owner Consent

Some capacity complaints are answered with software rather than hardware. A `ProgramAdmin` drafts a campaign, releases it to a fleet subset, collects each owner's consent, and records the flash when it is applied. The campaign's own lifecycle is derived from the aggregate state of its consent children.

A campaign is created with `campaign_code`, `target_defect` (`CHARGING` for charge-control defects or `THERMAL_MANAGEMENT` for cooling-control defects), `software_version`, `applies_to_pack_type` (`NEW`, `REMANUFACTURED`, or `ANY`, which matches both), `applies_to_model_code` naming the exact vehicle `model_code` targeted, an optional `consent_required` defaulting to true, and an optional `pilot_region_codes` array defaulting to empty. `campaign_code` must be unique across all campaigns, or the creation is refused with `ERR_DUPLICATE_CAMPAIGN_CODE`. A new campaign starts in `status` `DRAFT` with a null `release_scope` and all three counters — `solicited_consent_count`, `open_consent_count` and `applied_count` — at zero.

#### The release fork

Releasing a `DRAFT` campaign requires a `release_scope`, and the two branches diverge in exactly one respect: which vehicles get solicited. Both branches solicit by the same core filter — the vehicle's `model_code` equals the campaign's `applies_to_model_code`, the vehicle's `status` is `ACTIVE`, and either `applies_to_pack_type` is `ANY` or the vehicle's installed pack's `pack_type` equals `applies_to_pack_type` — and both create one `PENDING` consent per eligible vehicle in ascending vehicle `created_at` order, then set both `solicited_consent_count` and `open_consent_count` to the number of consents created.

A `LIMITED` release moves the campaign to `LIMITED_RELEASE`, records `release_scope` as `LIMITED`, and intersects the core filter with the pilot regions: the vehicle's `region_code` must be a member of `pilot_region_codes`. It also requires `pilot_region_codes` to be non-empty, since a limited release with no pilot region would solicit nobody; an empty list is refused with `ERR_INVALID_REQUEST`. A `FIELD` release moves the campaign to `FIELD_RELEASE`, records `release_scope` as `FIELD`, and ignores `pilot_region_codes` entirely, whatever it contains. For the same fleet the limited branch's consent set is therefore always a subset of the field branch's, and an `IMMOBILIZED` vehicle is solicited under neither.

Both released states are equally valid grounds for everything downstream: consent solicitation, owner decisions, applying the flash and linking a software claim all accept `LIMITED_RELEASE` and `FIELD_RELEASE` identically.

#### Soliciting and re-soliciting consent

Consents are created two ways. A campaign release creates the first round in bulk, and an approved software claim cascade-creates one if none exists for its campaign-and-vehicle pair. Beyond that a `ProgramAdmin` may solicit again after a refusal or a lapse, supplying `campaign_id`, `vehicle_id`, `expected_campaign_version` and an optional `superseded_consent_id`.

Such a re-solicitation is checked in the order given by the precedence ladder. `expected_campaign_version` must equal the campaign's current `version`, or the request is refused with `ERR_STALE_CAMPAIGN_VERSION` and HTTP 412; this is the stale-version guard described in section 2.6 and it fires because some earlier accepted solicitation already advanced the campaign's `version`. The campaign's `status` must be `LIMITED_RELEASE` or `FIELD_RELEASE`, or the request is refused with `ERR_CAMPAIGN_NOT_RELEASED` — a `DRAFT`, `SUSPENDED` or `CLOSED` campaign solicits nothing. The vehicle's `status` must be `ACTIVE`, or the request is refused with `ERR_VEHICLE_IMMOBILIZED`. The vehicle must satisfy the campaign's targeting filter — `model_code` matching `applies_to_model_code`, the installed pack's `pack_type` matching `applies_to_pack_type` with `ANY` matching both, and under a `LIMITED` release the vehicle's `region_code` being a member of `pilot_region_codes` — or the request is refused with `ERR_VEHICLE_NOT_TARGETED`. Finally no consent with `consent_status` `PENDING` or `GRANTED` may already exist for the same campaign-and-vehicle pair, and any supplied `superseded_consent_id` must point at a consent for that same pair whose `consent_status` is `DECLINED` or `EXPIRED`; a violation of either half is refused with `ERR_DUPLICATE_ACTIVE_CONSENT`.

An accepted solicitation creates the consent in `PENDING`, sets `expires_at` to its own `created_at` plus fourteen days, and sets `solicitation_round` to the superseded consent's `solicitation_round` plus one when one was named and to 1 otherwise. It raises the campaign's `solicited_consent_count` and `open_consent_count` each by one, and raises the campaign's `version` by one. `decision_at`, `applied_at` and `applied_software_version` all start null.

#### The owner's decision

The vehicle owner records a `decision` of `GRANT` or `DECLINE`, with an optional `owner_signature`. The acting `X-User-ID` must equal the consent's `vehicle_id`. The consent's `consent_status` must be `PENDING`, or the decision is refused with `ERR_CONSENT_ALREADY_DECIDED`; the vehicle's `status` must be `ACTIVE`, or it is refused with `ERR_VEHICLE_IMMOBILIZED`; and the current logical clock must be at or before `expires_at`, or it is refused with `ERR_CONSENT_EXPIRED` — a decision recorded at the exact expiry instant is accepted, since that boundary is inclusive. The campaign must also still be in `LIMITED_RELEASE` or `FIELD_RELEASE`. Either decision stamps `decision_at` with the current logical clock.

The two decisions differ sharply in their consequences. A `GRANT` moves `consent_status` to `GRANTED` and changes no counter at all, because `GRANTED` remains inside the open set alongside `PENDING`; the campaign's `open_consent_count` is therefore unchanged and no auto-close can be triggered by a grant.

A `DECLINE` moves `consent_status` to `DECLINED`, which is terminal, and lowers the campaign's `open_consent_count` by one. Because the open set shrank, the campaign auto-closes if `open_consent_count` has reached zero and at least one consent was ever solicited. And if a claim exists whose `vehicle_id` matches this consent's vehicle, whose `linked_campaign_id` matches this consent's campaign and whose `adjudication_status` is `APPROVED_SOFTWARE`, that claim collapses to `DENIED` with `denial_reason` set to `CONSENT_DECLINED`, its `remedy_cost_cents`, `owner_share_cents`, `oem_share_cents`, `admin_fee_cents` and `oem_total_cents` are reset to zero while its `approved_remedy` and `proration_factor` stand exactly as the adjudication left them — the collapse rewrites the money, not the remedy decision — and the program's `accrued_liability_cents` is reduced by the `oem_total_cents` that adjudication had booked. A refusal by the owner therefore unwinds the accrual exactly.

#### Applying the flash

A `ServiceTechnician` records the applied flash with an optional `installer_note`. The consent's `consent_status` must be `GRANTED` — `PENDING`, `DECLINED`, `EXPIRED` and `APPLIED` all reject with `ERR_CONSENT_NOT_GRANTED`. The vehicle's `status` must be `ACTIVE`, or `ERR_VEHICLE_IMMOBILIZED`. The current logical clock must be at or before `expires_at`, or `ERR_CONSENT_EXPIRED`; the fourteen-day window bounds the flash as well as the decision, so a consent granted on day one and flashed on day fifteen is refused even though the grant itself was timely. The campaign must be in `LIMITED_RELEASE` or `FIELD_RELEASE`, and the technician's `status` must be `ACTIVE` with an `hv_cert_level` of `L1`, `L2` or `L3` — a software flash is the one remedy any certified level may perform.

On success `consent_status` moves to `APPLIED`, `applied_at` is stamped with the current logical clock, and `applied_software_version` snapshots the campaign's `software_version` as it stands at that moment. The campaign's `applied_count` rises by one and its `open_consent_count` falls by one, and the campaign auto-closes if `open_consent_count` reaches zero. If a claim exists for the same vehicle and campaign in `APPROVED_SOFTWARE`, it moves to `FULFILLED` with `pack_shipment_required` set to false.

#### Suspension, expiry and the compound close

Consents also leave the open set without anyone acting. When a vehicle becomes `IMMOBILIZED`, its `PENDING` and `GRANTED` consents both move to `EXPIRED`. When a campaign is `SUSPENDED` by a severity-`S4` thermal event on a matching model, only its `PENDING` consents move to `EXPIRED`; `GRANTED` consents are deliberately left untouched, and since a suspended campaign cannot be released again, those grants simply cannot be flashed. Each expiry lowers `open_consent_count` by one.

`open_consent_count` is by definition the number of this campaign's consents in `PENDING` or `GRANTED`, and `applied_count` the number in `APPLIED`, while `solicited_consent_count` is a lifetime total that never falls. A campaign in `LIMITED_RELEASE` or `FIELD_RELEASE` auto-transitions to `CLOSED`, freezing `applied_count`, when and only when `solicited_consent_count` is at least one and `open_consent_count` is zero — so a campaign released to an empty eligible fleet stays open rather than closing immediately, and a `SUSPENDED` campaign never auto-closes however empty its open set becomes.

### 3.9. Capacity Disputes, Independent Verification and Remedy Reversals

An owner who disagrees with the manufacturer's capacity measurement may have it checked by an independent laboratory. The dispute is a child of the claim, and its outcome can reverse the adjudication in either direction.

The owner files the dispute with `claim_id`, `lab_name`, `owner_statement` and `expected_claim_version`, all four required, and the acting `X-User-ID` must equal the claim's `vehicle_id`. `expected_claim_version` must equal the claim's current `version`, or the filing is refused with `ERR_STALE_CLAIM_VERSION` and HTTP 412; a claim whose `version` has moved on since the owner read it — because an earlier dispute filing bumped it, for instance — must be re-read before the filing can succeed. The claim's `adjudication_status` must be one of `APPROVED_MODULE`, `APPROVED_PACK`, `APPROVED_SOFTWARE`, `DENIED` or `FULFILLED`, or the filing is refused with `ERR_CLAIM_NOT_DISPUTABLE`: a claim still under adjudication in `SUBMITTED` or `INFO_REQUESTED` has nothing to dispute yet, and a `CLOSED` claim has passed out of reach. No other dispute on the same claim may be in `LAB_ASSIGNED` or `LAB_RESULT_RECEIVED`, or the filing is refused with `ERR_DUPLICATE_ACTIVE_DISPUTE` — a claim whose earlier dispute was resolved may be disputed again. Finally the current logical clock must be at or before the claim's adjudication instant plus the program's `dispute_window_days` days, or the filing is refused with `ERR_DISPUTE_WINDOW_EXPIRED`; the boundary instant is inclusive, so a filing exactly thirty days after adjudication under the default window is accepted.

An accepted filing creates the dispute in `LAB_ASSIGNED` with `retest_count` 0, and snapshots two numbers from the claim's backing assessment: `nominal_basis_kwh`, which becomes the denominator for every later lab computation, and `retention_pct`, stored as `oem_retention_pct`, which is the figure the lab's result will be measured against. Both are frozen at filing time, so a later assessment on the same vehicle cannot move the goalposts. `lab_measured_capacity_kwh`, `lab_retention_pct`, `deviation_pct`, `resolution_note` and `resolved_by_user_id` all start null. The filing also raises the claim's `version` by one.

#### The laboratory result and the mandatory retest

The `IndependentLab` records `lab_measured_capacity_kwh` and an optional `lab_report_reference`. The dispute's `dispute_status` must be `LAB_ASSIGNED` or `LAB_RESULT_RECEIVED`, or the submission is refused with `ERR_DISPUTE_RESOLVED` — a resolved dispute accepts no further result.

Two figures are derived. `lab_retention_pct` is `lab_measured_capacity_kwh` divided by the dispute's `nominal_basis_kwh`, multiplied by one hundred, rounded half up to two decimals. `deviation_pct` is `lab_retention_pct` less `oem_retention_pct`, rounded half up to two decimals, and it is *signed*: a negative deviation means the lab found less capacity than the manufacturer did, which favours the owner; a positive deviation means the lab found more, which favours the manufacturer.

What happens next depends on the magnitude of the deviation and on whether a retest has already been ordered. If the absolute value of `deviation_pct` exceeds the program's `lab_tolerance_pct` *and* `retest_count` is still 0, the result is stored but the dispute does not advance: `retest_count` rises to 1 and `dispute_status` stays `LAB_ASSIGNED` awaiting exactly one mandatory retest, because a materially deviating first measurement must be confirmed before it can move a remedy. In every other case — the deviation is within tolerance, or `retest_count` is already 1 — the dispute moves to `LAB_RESULT_RECEIVED`.

A retest supersedes the first result rather than averaging with it: `lab_measured_capacity_kwh`, `lab_retention_pct` and `deviation_pct` all reflect the most recent result by `created_at`, and it is that most recent result alone which the resolution reads. So a first result far outside tolerance followed by a retest inside tolerance yields an upheld resolution, and `retest_count` remains 1 as the record that a retest was ordered.

#### Resolution and the two-person rule

A `WarrantyAdjudicator` resolves the dispute with a required `resolution_note`. The `dispute_status` must be `LAB_RESULT_RECEIVED`; a dispute in `LAB_ASSIGNED` — including one bounced back for a mandatory retest — is refused with `ERR_LAB_RESULT_REQUIRED`, and an already-resolved dispute is refused with `ERR_DISPUTE_RESOLVED`. The acting `X-User-ID` must differ from the claim's `adjudicated_by_user_id`, or the resolution is refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403: the adjudicator who decided the claim may not sit in judgement on the challenge to that decision. On success `resolution_note` is recorded and `resolved_by_user_id` is set to the acting `X-User-ID`.

The outcome is read off the latest `deviation_pct` against the program's `lab_tolerance_pct`, with symmetric bands whose boundaries fall on the upheld side. A `deviation_pct` strictly below the negative of `lab_tolerance_pct` yields `RESOLVED_OVERTURNED`. A `deviation_pct` strictly above `lab_tolerance_pct` yields `RESOLVED_DOWNGRADED`. Everything in between, boundaries included, yields `RESOLVED_UPHELD` — so with the default tolerance of 2.00 a deviation of exactly minus 2.00 or exactly plus 2.00 upholds the original decision, and only minus 2.01 or plus 2.01 disturbs it. All three outcomes are terminal.

`RESOLVED_UPHELD` touches the claim not at all: no state change, no settlement change, no ledger movement.

The other two outcomes drive reversal edges on the claim, and which edge fires depends on the claim's current state.

`RESOLVED_OVERTURNED` on a `DENIED` claim returns that claim to `SUBMITTED`, raises its `reopened_count` by one, and clears `approved_remedy`, `denial_reason` and `adjudicated_by_user_id` so the claim re-enters adjudication with a clean slate — and, because `adjudicated_by_user_id` is now null, the next adjudicator may be anyone. `RESOLVED_OVERTURNED` on an `APPROVED_MODULE` claim escalates it to `APPROVED_PACK`: the selector runs and must return a candidate, the selected pack moves from `STOCK` to `RESERVED`, the claim's `approved_remedy` is rewritten to `PACK_REPLACEMENT`, the program's `reman_available_count` falls and `reman_stock_state` is refreshed, and the ledger is corrected by subtracting the old `oem_total_cents` from `accrued_liability_cents`, recomputing the whole settlement for a pack replacement, and adding the new `oem_total_cents`.

`RESOLVED_DOWNGRADED` on an `APPROVED_PACK` claim collapses it to `APPROVED_MODULE`: the reserved pack returns from `RESERVED` to `STOCK`, the program's `reman_available_count` rises by one, `reman_stock_state` becomes `AVAILABLE` because the count is now above zero, the claim's `replacement_pack_id` is cleared, its `approved_remedy` is rewritten to `MODULE_REPLACEMENT`, and the ledger is corrected by subtracting the old `oem_total_cents`, recomputing the settlement for a module replacement, and adding the new `oem_total_cents`. `RESOLVED_DOWNGRADED` on an `APPROVED_MODULE` claim collapses it to `DENIED`: the claim's `oem_total_cents` is subtracted from `accrued_liability_cents`, then `remedy_cost_cents`, `owner_share_cents`, `oem_share_cents` and `oem_total_cents` are all set to zero and `denial_reason` is set to `DISPUTE_DOWNGRADE`. This collapse deliberately zeroes four money fields and not five: `admin_fee_cents` keeps the figure the adjudication computed, as do `proration_factor` and `approved_remedy`, so a dispute-driven denial is not byte-identical to the adjudicator's own denial. `DISPUTE_DOWNGRADE` distinguishes a dispute-driven denial from the `ADJUDICATOR_DECISION` of an original refusal and from the `CONSENT_DECLINED` of a refused software remedy.

In every reversal the ledger correction is a subtract-then-recompute-then-add sequence, never an in-place adjustment of the difference, so the program's `accrued_liability_cents` always equals the sum of the current `oem_total_cents` of every accruing claim.

### 3.10. Removed-Pack Logistics and Hazardous Materials Shipping

A lithium-ion traction pack that has been out of a vehicle is dangerous goods. Every removed or quarantined pack that leaves a service center travels on a shipment record whose hazardous-materials declaration is computed once, at creation, and frozen.

A `ServiceTechnician` creates the shipment with `pack_id`, `origin_service_center_id`, `certifying_technician_id`, `shipment_contents` (`FULL_PACK` when the whole pack ships, `MODULES_ONLY` when only the removed modules do), `packaging_spec` (`STANDARD_UN_4G` or `SP376_STRONG_OUTER`, recording the packaging actually used) and `state_of_charge_pct`, all required, plus an optional `transport_mode` (`GROUND` or `AIR`, defaulting to `GROUND`) and an optional `destination` (`REMAN_CENTER` for refurbishment intake or `RECYCLER` for scrap, defaulting to `REMAN_CENTER`). `state_of_charge_pct` is a two-decimal percentage between 0.00 and 100.00.

The pack's `status` must be `REMOVED` or `QUARANTINED`; a pack still `IN_SERVICE`, or in `STOCK`, `RESERVED` or `SCRAPPED`, is refused with `ERR_SHIPMENT_PACK_NOT_REMOVED`. The origin center's `status` must be `ACTIVE`; a center in `SHIPPING_SUSPENDED` or `DECERTIFIED` cannot tender hazardous freight and is refused with `ERR_CENTER_SHIPPING_SUSPENDED`. The certifying technician must belong to the origin center — enforced by `ERR_TECHNICIAN_CENTER_MISMATCH` — with `status` `ACTIVE` and an `hv_cert_level` of `L2` or `L3`. And the hazmat two-person rule applies: `certifying_technician_id` must differ from the `fulfilment_technician_id` of any claim whose removed pack or `replacement_pack_id` is this pack, or the creation is refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403. The technician who pulled the pack may not also sign its shipper certification.

#### The frozen declaration

Creation computes five fields from the pack's condition and the declared contents, in a pinned order in which the pack's damage dominates what is actually in the box.

`hazmat_classification` is `UN3536` whenever the pack's `damaged_defective` flag is true, whatever `shipment_contents` says. Only if the pack is undamaged does the contents decide: `UN3480` for a `FULL_PACK` shipment of batteries alone, `UN3481` for a `MODULES_ONLY` shipment. A `MODULES_ONLY` shipment of a damaged pack is therefore `UN3536`, not `UN3481`.

`required_packaging_spec` follows directly: `SP376_STRONG_OUTER` when the classification is `UN3536`, and `STANDARD_UN_4G` for `UN3480` and `UN3481` alike.

`soc_limit_pct` is 30.00 when the classification is `UN3536` *or* the `transport_mode` is `AIR`, and 50.00 otherwise. Either condition alone pulls the limit down to 30.00; they do not compound.

`gross_weight_kg` is the declared shipping weight to three decimals. For a `FULL_PACK` shipment it is simply the pack's own `gross_weight_kg`. For a `MODULES_ONLY` shipment it is the pack's `gross_weight_kg` scaled by the number of that pack's modules whose `status` is `REPLACED` over the pack's `module_count`, rounded half up to three decimals — so the box's declared weight tracks how many modules actually came out.

`hazmat_fee_cents` is the surcharge basis multiplied by `gross_weight_kg` and divided by one hundred, rounded half up to whole cents, the surcharges being quoted per 100 kilograms. The basis is the program's `surcharge_un3536_cents` for `UN3536`, its `surcharge_un3480_cents` for `UN3480`, and its `surcharge_un3481_cents` for `UN3481`.

All five are frozen at creation. If the pack is later flagged `damaged_defective` — by a thermal event, say — an existing shipment's `hazmat_classification` is *not* recomputed, and it continues to travel on the declaration it was created with. The shipment starts in `status` `DRAFT` with null `tendered_at`, `received_at`, `disposition` and `rejection_reason`.

One safety rule bites at creation rather than at tender: air transport of a damaged pack is prohibited outright. If `hazmat_classification` is `UN3536` and `transport_mode` is `AIR`, the creation is refused with `ERR_AIR_TRANSPORT_FORBIDDEN`.

#### Tendering to the carrier

A `ServiceTechnician` tenders the shipment with an optional `carrier_reference`. The `status` must be `DRAFT`; a shipment already tendered, received or rejected is refused with `ERR_SHIPMENT_NOT_TENDERED`, which is also the error a receipt attempt receives when the shipment is not in `TENDERED`. The origin center must still be `ACTIVE`, or `ERR_CENTER_SHIPPING_SUSPENDED` — a center suspended between creation and tender cannot tender the freight it had already prepared. The certifying technician's `cert_expires_at` must still be strictly later than the current logical clock, or the tender is refused with `ERR_TECHNICIAN_CERT_EXPIRED`.

Two conformance checks then run against the frozen declaration. `packaging_spec` must equal `required_packaging_spec`, or the tender is refused with `ERR_PACKAGING_NONCONFORMANT` — shipping a damaged pack in standard packaging is refused here, at the moment of handover, not at creation. And `state_of_charge_pct` must be at or below `soc_limit_pct`, or the tender is refused with `ERR_SOC_LIMIT_EXCEEDED`; the boundary value is accepted, so exactly 30.00 against a 30.00 limit passes. On success the `status` moves to `TENDERED` and `tendered_at` is stamped with the current logical clock.

#### Receipt at the destination

A `ProgramAdmin` records receipt with an `outcome` of `ACCEPTED` or `REJECTED`, plus exactly one of the two companions: `disposition` for an acceptance or `rejection_reason` for a rejection. The `status` must be `TENDERED`, or the receipt is refused with `ERR_SHIPMENT_NOT_TENDERED`. Either outcome stamps `received_at` with the current logical clock.

An **acceptance** requires `disposition`, which must be `REMANUFACTURE` or `SCRAP`. A `REMANUFACTURE` disposition requires the `destination` to be `REMAN_CENTER` and a `refurb_soh_pct` in the payload; a `SCRAP` disposition requires the `destination` to be `RECYCLER`. The shipment moves to `RECEIVED` with the `disposition` recorded, and the pack follows.

On `REMANUFACTURE` the pack returns to inventory: its `status` moves from `REMOVED` — or from `QUARANTINED` — to `STOCK`, its `pack_type` becomes `REMANUFACTURED`, its `remanufacture_count` rises by one, its `refurb_soh_pct` is set from the receipt payload, its `damaged_defective` flag is cleared, and every one of its modules is returned to `HEALTHY`. Because a remanufactured pack has entered `STOCK`, the program's `reman_available_count` rises by one and `reman_stock_state` is refreshed to `AVAILABLE`. The receipt does not touch the pack's `installed_vehicle_id`: a pack quarantined by a thermal event while still fitted therefore returns to `STOCK` still naming that vehicle, since only a pack-replacement fulfilment nulls that field. If the pack had been quarantined, the origin center's `open_hazmat_holds` falls by one, floored at zero.

On `SCRAP` the pack moves from `REMOVED` or `QUARANTINED` to `SCRAPPED`, which is terminal: every module's `status` is set to `REPLACED` and the pack's `hazmat_classification` is cleared. A scrapped pack never returns to stock, so `reman_available_count` does not move. If the pack had been quarantined, the origin center's `open_hazmat_holds` falls by one, floored at zero.

A **rejection** requires `rejection_reason`, one of `PACKAGING_NONCONFORMANT`, `SOC_OUT_OF_LIMIT` or `DOCUMENTATION_MISSING`. The shipment moves to `REJECTED`, also terminal, and the compliance cascade of section 2.8 fires: the pack is set to `QUARANTINED` whatever its status before the rejection, with `damaged_defective` set to true and `hazmat_classification` set to `UN3536`; the origin center's `open_hazmat_holds` rises by one — a pack already in quarantine is not exempt — and, if that reaches two while the center is `ACTIVE`, the center moves to `SHIPPING_SUSPENDED` and every claim at that center in `APPROVED_MODULE` or `APPROVED_PACK` has `fulfilment_blocked` set to true; and the center's `rejected_shipment_count` rises by one with its `compliance_score` recomputed, decertifying the center if the recomputed score is at or below twenty. A single rejection therefore leaves the center working — one rejected shipment scores 85 and holds one hazmat hold — while a second rejection both suspends shipping and drops the score to 70.

Because the rejection returns the pack to `QUARANTINED` rather than to `REMOVED`, a re-tender needs a fresh shipment record, whose declaration will now classify as `UN3536` and demand `SP376_STRONG_OUTER` packaging even if the original box was `UN3481`. When that replacement shipment is eventually received, the hold clears and the center returns to `ACTIVE` of its own accord, unblocking the claims that had been frozen.

## 4. Endpoint Definitions

Every path below is prefixed with `/battery-warranty`. Endpoints that create a resource return HTTP 201; endpoints that read or modify a resource return HTTP 200. Every field marked optional in section 3 may be omitted from the request body, in which case the documented default applies; every field described as required must be present and non-null. Error responses use the status codes catalogued in section 5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/battery-warranty/warranty-programs` | Register a capacity-retention warranty program. Every constant carries a reference default, so only the program name is required. | ProgramAdmin |
| GET | `/battery-warranty/warranty-programs/{program_id}` | Read a warranty program, including its accrued-liability and remanufactured-stock mirrors. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| POST | `/battery-warranty/vehicles` | Register a vehicle under a warranty program. | ProgramAdmin |
| GET | `/battery-warranty/vehicles/{vehicle_id}` | Read a vehicle, including its installed-pack mirror. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| GET | `/battery-warranty/vehicles` | List vehicles, filterable by program, status and model code. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| POST | `/battery-warranty/service-centers` | Register a high-voltage service center. | ProgramAdmin |
| GET | `/battery-warranty/service-centers/{center_id}` | Read a service center, including its compliance score and certification standing. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| GET | `/battery-warranty/service-centers` | List service centers, filterable by region, status and certification level. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| POST | `/battery-warranty/service-centers/{id}/technicians` | Register a technician at a center. | ProgramAdmin |
| GET | `/battery-warranty/service-centers/{id}/technicians` | List a center's technicians; certification standing is re-derived against the logical clock on every read. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| POST | `/battery-warranty/battery-packs` | Register a battery pack; its modules are cascade-created healthy and are reachable only through the pack's module sub-resource. | ProgramAdmin |
| GET | `/battery-warranty/battery-packs/{pack_id}` | Read a battery pack, including its faulted-module and lifetime-replacement counters. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| GET | `/battery-warranty/battery-packs` | List battery packs, filterable by installation, supersession chain, status, type and stock region. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| GET | `/battery-warranty/battery-packs/{id}/modules` | List a pack's modules in ascending position order. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| POST | `/battery-warranty/vehicles/{id}/telematics-snapshots` | Ingest one telematics snapshot; an immutable event row with no version and no update path. | TelematicsGateway |
| GET | `/battery-warranty/vehicles/{id}/telematics-snapshots` | List a vehicle's telematics snapshots, newest capture first, filterable by validity. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, TelematicsGateway, VehicleOwner, IndependentLab, RegulatoryLiaison |
| POST | `/battery-warranty/soh-assessments` | Run a state-of-health assessment. Requires the vehicle's current version for the stale-version guard. | ServiceTechnician |
| GET | `/battery-warranty/soh-assessments/{assessment_id}` | Read a state-of-health assessment. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| GET | `/battery-warranty/soh-assessments` | List assessments, filterable by vehicle, pack, technician, variant, validity and supersession. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| POST | `/battery-warranty/warranty-claims` | File a warranty claim against a qualifying assessment. | ServiceTechnician |
| GET | `/battery-warranty/warranty-claims/{claim_id}` | Read a warranty claim, including its full settlement breakdown. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| GET | `/battery-warranty/warranty-claims` | List warranty claims, filterable by all seven of the claim's foreign keys and by adjudication status. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| POST | `/battery-warranty/warranty-claims/{claim_id}/request-info` | Open an information-request round on a submitted claim. | WarrantyAdjudicator |
| POST | `/battery-warranty/warranty-claims/{claim_id}/resubmit` | Answer an information request and return the claim to adjudication, recomputing the remedy recommendation. | ServiceTechnician |
| POST | `/battery-warranty/warranty-claims/{claim_id}/adjudicate` | Decide a claim; runs the settlement waterfall and, for a pack approval, the remanufactured-pack selector. | WarrantyAdjudicator |
| POST | `/battery-warranty/warranty-claims/{claim_id}/fulfil` | Execute the approved remedy inside a booked high-voltage bay window. | ServiceTechnician |
| POST | `/battery-warranty/warranty-claims/{claim_id}/close` | Close a fulfilled or denied claim. Terminal. | WarrantyAdjudicator |
| GET | `/battery-warranty/warranty-claims/{id}/capacity-disputes` | List the capacity disputes filed against a claim. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| POST | `/battery-warranty/thermal-events` | Report a thermal event, opening the independent containment and notification dimensions. | ServiceTechnician, TelematicsGateway |
| GET | `/battery-warranty/thermal-events/{event_id}` | Read a thermal event with both state dimensions and the derived join field. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, TelematicsGateway, VehicleOwner, IndependentLab, RegulatoryLiaison |
| GET | `/battery-warranty/thermal-events` | List thermal events, filterable by vehicle, pack, severity, both dimensions and reporting center. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, TelematicsGateway, VehicleOwner, IndependentLab, RegulatoryLiaison |
| POST | `/battery-warranty/thermal-events/{event_id}/containment-step` | Record the next containment step; steps may be neither skipped nor repeated. | ServiceTechnician |
| POST | `/battery-warranty/thermal-events/{event_id}/regulatory-notification` | File the regulatory notification for a reportable event. | RegulatoryLiaison |
| POST | `/battery-warranty/remediation-campaigns` | Create a software remediation campaign in draft. | ProgramAdmin |
| GET | `/battery-warranty/remediation-campaigns/{campaign_id}` | Read a campaign with its three solicitation counters. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| GET | `/battery-warranty/remediation-campaigns` | List campaigns, filterable by status, target defect and target model code. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| POST | `/battery-warranty/remediation-campaigns/{campaign_id}/release` | Release a draft campaign; the limited scope restricts solicitation to the pilot regions while the field scope opens every region. | ProgramAdmin |
| POST | `/battery-warranty/remediation-consents` | Solicit an owner's consent for a released campaign. Requires the campaign's current version for the stale-version guard. | ProgramAdmin |
| GET | `/battery-warranty/remediation-consents/{consent_id}` | Read a consent record. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| GET | `/battery-warranty/remediation-consents` | List consents, filterable by campaign, vehicle, supersession chain and status. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| POST | `/battery-warranty/remediation-consents/{consent_id}/decision` | Record the owner's grant or refusal; a refusal collapses any linked software approval and reverses its accrual. | VehicleOwner |
| POST | `/battery-warranty/remediation-consents/{consent_id}/apply-update` | Record the applied software flash against a granted consent. | ServiceTechnician |
| POST | `/battery-warranty/capacity-disputes` | File a capacity dispute against an adjudicated claim. Requires the claim's current version for the stale-version guard. | VehicleOwner |
| GET | `/battery-warranty/capacity-disputes/{dispute_id}` | Read a capacity dispute with its latest laboratory measurement and signed deviation. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| POST | `/battery-warranty/capacity-disputes/{dispute_id}/lab-result` | Record an independent-laboratory measurement; a first result beyond tolerance mandates one retest. | IndependentLab |
| POST | `/battery-warranty/capacity-disputes/{dispute_id}/resolve` | Resolve a dispute. The resolver must differ from the adjudicator who decided the claim. | WarrantyAdjudicator |
| POST | `/battery-warranty/pack-shipments` | Create a removed-pack shipment in draft; classification, packaging requirement, weight, fee and charge limit are frozen here. | ServiceTechnician |
| GET | `/battery-warranty/pack-shipments/{shipment_id}` | Read a pack shipment with its frozen hazardous-materials declaration. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| GET | `/battery-warranty/pack-shipments` | List pack shipments, filterable by pack, origin center, certifying technician, status and classification. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, VehicleOwner, IndependentLab, RegulatoryLiaison |
| POST | `/battery-warranty/pack-shipments/{shipment_id}/tender` | Tender the shipment to the carrier, validating packaging conformance and state of charge against the frozen declaration. | ServiceTechnician |
| POST | `/battery-warranty/pack-shipments/{shipment_id}/receive` | Record receipt at the destination, supplying either a disposition or a rejection reason. | ProgramAdmin |
| POST | `/battery-warranty/_clock/set_current_utc` | Test-driving endpoint. Set the server's logical clock via `current_utc`. Before any call the clock reads exactly `2026-08-01T00:00:00Z` and never falls back to wall-clock time; it never rewinds. | ProgramAdmin |

## 5. Error Code Catalogue

Every rejection returns the error envelope of section 2.2 with one of the identifiers below in its `error_id` field. When more than one rule is violated by a single request, the identifier returned is the one whose position in the precedence ladder of section 2.7 is earliest.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_ACTOR_REQUIRED` | 400 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_BENCH_CAPACITY_REQUIRED` | 400 |
| `ERR_DETECTED_AT_IN_FUTURE` | 400 |
| `ERR_INVALID_BAY_WINDOW` | 400 |
| `ERR_MODULE_POSITION_INVALID` | 422 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_VEHICLE_NOT_FOUND` | 404 |
| `ERR_PACK_NOT_FOUND` | 404 |
| `ERR_CENTER_NOT_FOUND` | 404 |
| `ERR_TECHNICIAN_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_CONSENT_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_STALE_VEHICLE_VERSION` | 412 |
| `ERR_STALE_CLAIM_VERSION` | 412 |
| `ERR_STALE_CAMPAIGN_VERSION` | 412 |
| `ERR_DUPLICATE_VIN` | 409 |
| `ERR_DUPLICATE_PACK_SERIAL` | 409 |
| `ERR_DUPLICATE_CAMPAIGN_CODE` | 409 |
| `ERR_CLAIM_TERMINAL` | 409 |
| `ERR_CLAIM_NOT_ADJUDICABLE` | 409 |
| `ERR_INFO_REQUEST_NOT_OPEN` | 409 |
| `ERR_CLAIM_NOT_FULFILLABLE` | 409 |
| `ERR_CLAIM_NOT_CLOSABLE` | 409 |
| `ERR_CLAIM_NOT_DISPUTABLE` | 409 |
| `ERR_DISPUTE_RESOLVED` | 409 |
| `ERR_LAB_RESULT_REQUIRED` | 409 |
| `ERR_CONTAINMENT_STEP_OUT_OF_ORDER` | 409 |
| `ERR_NOTIFICATION_STILL_PENDING` | 409 |
| `ERR_NOTIFICATION_ALREADY_FILED` | 409 |
| `ERR_CAMPAIGN_NOT_RELEASED` | 409 |
| `ERR_CONSENT_ALREADY_DECIDED` | 409 |
| `ERR_CONSENT_NOT_GRANTED` | 409 |
| `ERR_VEHICLE_IMMOBILIZED` | 409 |
| `ERR_ASSESSMENT_SUPERSEDED` | 409 |
| `ERR_ASSESSMENT_ALREADY_CLAIMED` | 409 |
| `ERR_DIAGNOSTIC_NOT_VALID` | 409 |
| `ERR_SHIPMENT_PACK_NOT_REMOVED` | 409 |
| `ERR_SHIPMENT_NOT_TENDERED` | 409 |
| `ERR_CENTER_SHIPPING_SUSPENDED` | 409 |
| `ERR_PACK_VEHICLE_MISMATCH` | 422 |
| `ERR_ASSESSMENT_VEHICLE_MISMATCH` | 422 |
| `ERR_TECHNICIAN_CENTER_MISMATCH` | 422 |
| `ERR_VEHICLE_NOT_TARGETED` | 422 |
| `ERR_PACK_REGION_MISMATCH` | 422 |
| `ERR_CENTER_NOT_CERTIFIED` | 409 |
| `ERR_CENTER_CERT_LEVEL_INSUFFICIENT` | 409 |
| `ERR_PACK_LIFT_REQUIRED` | 409 |
| `ERR_INSULATION_TESTER_OVERDUE` | 409 |
| `ERR_TECHNICIAN_CERT_EXPIRED` | 409 |
| `ERR_TECHNICIAN_LEVEL_INSUFFICIENT` | 409 |
| `ERR_THERMAL_CONTAINMENT_OPEN` | 409 |
| `ERR_REMEDY_OVERRIDE_FORBIDDEN` | 409 |
| `ERR_AIR_TRANSPORT_FORBIDDEN` | 409 |
| `ERR_PACKAGING_NONCONFORMANT` | 409 |
| `ERR_SOC_LIMIT_EXCEEDED` | 409 |
| `ERR_CLOCK_REWIND_FORBIDDEN` | 409 |
| `ERR_HV_BAY_CAPACITY_EXCEEDED` | 409 |
| `ERR_TECHNICIAN_COOLDOWN_CONFLICT` | 409 |
| `ERR_CONSENT_EXPIRED` | 409 |
| `ERR_DISPUTE_WINDOW_EXPIRED` | 409 |
| `ERR_VEHICLE_ALREADY_HAS_PACK` | 409 |
| `ERR_CLAIM_ALREADY_OPEN` | 409 |
| `ERR_RETENTION_ABOVE_THRESHOLD` | 409 |
| `ERR_OUT_OF_COVERAGE` | 409 |
| `ERR_INFO_REQUEST_LIMIT_EXCEEDED` | 409 |
| `ERR_DUPLICATE_ACTIVE_CONSENT` | 409 |
| `ERR_DUPLICATE_ACTIVE_DISPUTE` | 409 |
| `ERR_NOTIFICATION_NOT_REQUIRED` | 409 |
| `ERR_PACK_NOT_IN_STOCK` | 409 |
| `ERR_NO_REMAN_PACK_AVAILABLE` | 409 |
| `ERR_LIABILITY_CAP_EXCEEDED` | 409 |
