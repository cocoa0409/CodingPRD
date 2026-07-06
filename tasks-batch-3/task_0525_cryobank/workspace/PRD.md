# Cryobank & Donor Gamete Bank API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Cryobank & Donor Gamete Bank API, a back-office platform modeled on the operations of a California-style donor gamete bank. The system tracks the full journey of donated genetic material: a donor's application and FDA/genetic screening, the collection and cryopreservation of specimens into liquid-nitrogen (LN2) dewar inventory, publication of an anonymized donor catalog, the reservation and shipment of frozen vials to fertility clinics, recipient consent and quarantine release, long-term storage billing, a cross-family sibling registry, and periodic regulatory reporting.

The domain is unusually compliance-heavy. Regulatory holds, infectious-disease retesting, carrier-screening dispositions, and donor family limits all gate whether a given vial may ever leave the bank, and a single adverse screening decision must cascade through every downstream specimen, inventory lot, reservation, and shipment already in flight. Because multiple staff roles operate on shared inventory concurrently, the platform must also guard against two operators reserving the same physical vials from a stale view of availability. The requirements below describe the resources, their state machines, the financial and capacity calculations, and the validation rules that together enforce these guarantees.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, conventions, and cross-cutting principles that apply across every endpoint. The domain-specific business workflows that reference these principles are detailed in Section 3.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` does not name a recognized role, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes six roles, spelled exactly as follows: `ScreeningOfficer`, `LabTech`, `ComplianceOfficer`, `CatalogManager`, `Recipient`, and `BillingClerk`.

For five of these roles — `ScreeningOfficer`, `LabTech`, `ComplianceOfficer`, `CatalogManager`, and `BillingClerk` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record such an identifier where a workflow calls for it, but it does not compare the opaque identifier against any entity's `id`. When `X-User-Role` is `Recipient`, however, `X-User-ID` is the `id` of the acting `Recipient` entity; any ownership check on a resource that references a recipient (for instance, a reservation, consent, shipment, or storage account carrying a `recipient_id`) compares that resource's recipient foreign key against `X-User-ID`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — donors, screening applications, specimens, donor inventory lots, recipients, recipient consents, vial reservations, shipments, storage accounts, storage invoices, sibling-registry entries, collection appointments, dewar maintenance windows, and regulatory reports — carries a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that starts at its initial value on creation and increments by one on every mutation of the resource. It underpins the optimistic concurrency control described in §2.7.

Whenever a derived or computed field on a resource changes as a result of a workflow (for example, a donor inventory lot's `reserved_vials` or `available_vials` being recomputed, or a donor's `reported_family_count` being recounted), that change is itself a mutation: it refreshes `updated_at` and increments `version` on the mutated resource. All fifteen resource families above expose all four common fields.

### 2.5. Nested Resource Retrieval and Reference Resolution

Many operations reference other entities by identifier, either in the URL path or in the request body. The system validates every such identifier, and it does so left-to-right in the path before examining the body. If any referenced identifier does not resolve to an existing entity, the request is rejected with `ERR_NOT_FOUND`; the first unresolved identifier encountered in left-to-right path order determines the failure. This existence check precedes state and business-rule validation, so that a request naming a non-existent resource is never partially processed.

### 2.6. State Integrity and Cascading Consistency

Each entity carries a `status` field holding its current lifecycle state, and moves through a defined state machine (see Section 3). An action is only accepted when the target entity's `status` currently sits in a state from which the requested transition is defined; otherwise the request is rejected with `ERR_INVALID_STATE`. List endpoints that accept a `status` filter match against this same field. Beyond single-entity transitions, several operations mutate more than one entity at once. When a donor is deferred, or when a specimen is discarded, the effects cascade across the donor's specimens, inventory lots, reservations, and shipments as described in §3.2 and §3.4. Every entity touched by such a cascade is independently mutated — its `updated_at` is refreshed and its `version` is incremented — so that the platform remains internally consistent with immediate effect rather than through any deferred reconciliation.

### 2.7. Optimistic Concurrency Control on Vial Reservations

Donor inventory availability is a shared resource that several catalog operators and recipients may act on at the same time. To prevent a writer from overwriting availability it never observed, placing a new vial hold is guarded by optimistic concurrency control. The request that creates a vial reservation must carry `expected_inventory_version`, which is the value of the target donor inventory lot's `version` that the client last read. If the inventory lot's current `version` has advanced beyond that value — because another writer has since placed a hold that legitimately consumed some of the availability the current writer believed was free — the create is rejected with `ERR_STALE_INVENTORY_VERSION` at HTTP 412, and the client must re-fetch the lot before retrying. Only the reservation-create operation carries this version guard; no other endpoint takes a version field as input.

### 2.8. Storage Billing Precision

All monetary amounts in the system are expressed as integer cents; the `amount_cents` field on a storage invoice is always a whole number of cents. Wherever a billing computation produces a fractional cent — as happens when a renewal charge is prorated across a partial period — the result is rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway between two cents rounds up). The concrete billing formulas, including the annual per-vial rate and the proration mechanics, are given in §3.7.

### 2.9. Positive-Integer and Interval Input Rules

Several fields must be supplied as strictly positive integers: `initial_vial_count` on a specimen, `vial_count` on a vial reservation, `family_limit` on a donor, and `stored_vials` on a storage account must each be at least 1. The `genetic_carrier_count` on a screening application must be at least 0. For any booked interval, the end must be strictly later than the start — that is, `window_end` must be after `window_start` on a collection appointment. When a required field is absent, an enum value is not one of the permitted strings, or one of these numeric constraints is violated, the create is rejected with `ERR_INVALID_REQUEST` at HTTP 400.

### 2.10. Validation Ordering

When several checks apply to the same operation, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every referenced identifier (`ERR_NOT_FOUND`), then whether the requested transition is legal from the entity's current state (`ERR_INVALID_STATE`). Only after those four gates does the system evaluate the operation-specific business rules described in Section 3. The most consequential ordering appears at reservation creation, where the business checks themselves run in a fixed sequence detailed in §3.4: consent presence, then family limit, then inventory listability, then vial availability, and finally the stale-version guard. Field-shape validation (`ERR_INVALID_REQUEST`) guards the well-formedness of create payloads.

## 3. Business Logic & Workflows

### 3.1. Donor Intake and Screening

Every donor begins as an applicant. A `ScreeningOfficer` registers a donor by supplying a public catalog code `display_code` (for example `D-14829`), the donor's legal `full_name` (which is never surfaced in the public catalog), the `donor_type` — one of `SPERM` or `OOCYTE` — the `blood_type` — one of `A_POS`, `A_NEG`, `B_POS`, `B_NEG`, `AB_POS`, `AB_NEG`, `O_POS`, or `O_NEG` — and the donor's `family_limit`, the maximum number of distinct recipient families that may ever be served by this donor. A freshly registered donor enters status `APPLICANT`, with `reported_family_count` initialized to 0, `fda_eligible` and `genetic_panel_clear` both false by default, and `is_family_limit_reached` false. A donor's overall lifecycle runs `APPLICANT` → `SCREENING` → `APPROVED`, then `ACTIVE` once material is released to the catalog, with `DEFERRED` and `RETIRED` as off-ramps.

Screening is tracked by a separate `ScreeningApplication`. A `ScreeningOfficer` submits one by naming the `donor_id`, the questionnaire outcome `fda_risk_flag` (defaulting to false), the `genetic_carrier_count` — the number of pathogenic carrier variants found in the panel, which must be at least 0 — and `partner_screening_required` (defaulting to false, and set true when carrier variants were found and the disposition calls for partner testing). An optional `decision_note` may accompany the officer's approve or defer decision. A new application enters `SUBMITTED`.

When the officer begins review, the application advances `SUBMITTED` → `UNDER_REVIEW`, and as a side effect the donor moves from `APPLICANT` to `SCREENING`. From `UNDER_REVIEW` the application forks two ways. Approval advances it `UNDER_REVIEW` → `APPROVED`: this requires that the application be in `UNDER_REVIEW`, that `fda_risk_flag` is false, and that it is not the case that carrier variants were found and partner testing is still outstanding — concretely, approval is permitted when `genetic_carrier_count` equals 0 or `partner_screening_required` is false. On approval the donor's status becomes `APPROVED`, its `fda_eligible` flag is set to true, and its `genetic_panel_clear` flag is set to true exactly when the application's `genetic_carrier_count` equals 0 (and false otherwise). If an approval is attempted while `fda_risk_flag` is true, it is rejected with `ERR_FDA_INELIGIBLE`. If an approval is attempted while `genetic_carrier_count` is greater than 0 and `partner_screening_required` is true, it is rejected with `ERR_GENETIC_SCREENING_INCOMPLETE`.

Deferral advances the application `UNDER_REVIEW` → `DEFERRED`, a terminal outcome, requiring only that the application currently be `UNDER_REVIEW`. The cascade that a deferral triggers on the donor's downstream material is described in §3.4.

### 3.2. Specimen Collection, Quarantine, and Inventory

Once a donor is `APPROVED`, a `LabTech` records each collection as a `Specimen` by supplying the `donor_id`, the `collection_date`, the `initial_vial_count` cryopreserved from that collection (a positive integer), the `quarantine_release_date` — the earliest UTC instant at which the mandatory 180-day FDA infectious-disease quarantine may be lifted — and `retest_negative` (defaulting to false), the flag that records whether the 180-day repeat infectious-disease retest came back negative. A new specimen enters `COLLECTED`.

To begin quarantine, a `LabTech` supplies the `dewar_code` naming the LN2 dewar or tank where the vials will be stored; this advances the specimen `COLLECTED` → `QUARANTINE` and requires that the specimen currently be `COLLECTED` and its donor be `APPROVED`. As a side effect, exactly one `DonorInventory` lot is minted for the specimen, with `total_vials` equal to the specimen's `initial_vial_count`, `available_vials` equal to that same count, `reserved_vials` and `shipped_vials` at 0, and `hold_status` set to `OPEN`. The inventory lot carries the `specimen_id` it was minted from and the `donor_id` it belongs to.

Releasing quarantine is a `ComplianceOfficer` action that advances the specimen `QUARANTINE` → `RELEASED`. It is permitted only when the specimen is in `QUARANTINE`, its `retest_negative` is true, the current logical time has reached the specimen's `quarantine_release_date` (that is, the current UTC instant is at or after `quarantine_release_date`), and the donor is `APPROVED`. A release attempt where `retest_negative` is still false is rejected with `ERR_RETEST_NOT_NEGATIVE`; a release attempt before the quarantine window has elapsed — the current UTC instant still earlier than `quarantine_release_date` — is rejected with `ERR_QUARANTINE_NOT_ELAPSED`. On the donor's first ever released specimen, the donor's status advances to `ACTIVE`. Release also recomputes the listability of that specimen's inventory lot.

A specimen may leave the pipeline by being discarded, advancing either `QUARANTINE` → `DISCARDED` or `RELEASED` → `DISCARDED`, with `DISCARDED` terminal. Discard occurs either through the donor-deferral cascade or by an explicit `ComplianceOfficer` discard action. When a specimen in `QUARANTINE` is discarded, every vial reservation in `HELD` or `CONFIRMED` on that specimen's inventory is voided to `CANCELLED` and the inventory counts are recomputed. When a specimen in `RELEASED` is discarded, the same voiding of `HELD` and `CONFIRMED` reservations to `CANCELLED` occurs, and in addition each such just-cancelled reservation that has a linked shipment in `PREPARING` or `DISPATCHED` drives that shipment to `CANCELLED`; the inventory counts and listability are then recomputed.

Deferring a donor's screening application (the `UNDER_REVIEW` → `DEFERRED` transition of §3.1) sets the donor's status to `DEFERRED` and cascades across all of the donor's material: every specimen of that donor not already `DISCARDED` is driven to `DISCARDED` (carrying with it, per the specimen-discard side effects above, the voiding of `HELD`/`CONFIRMED` reservations and cancellation of their in-flight shipments), and every `DonorInventory` lot of that donor has its `hold_status` set to `FROZEN`, which blocks any new reservation against it.

An inventory lot's readiness for catalog listing is captured by its computed `is_listed` flag. A lot is listed exactly when its specimen is `RELEASED`, its donor is `ACTIVE`, the donor has not reached its family limit (`is_family_limit_reached` is false), its `hold_status` is `OPEN`, and its `available_vials` is greater than 0. The lot also exposes a computed `committed_available_vials`, described alongside the availability arithmetic in §3.5.

### 3.3. Recipient Registration and Consent

A recipient family is registered — by either a `CatalogManager` or the `Recipient` themselves — with a `family_name` and a `contact_email`. A new recipient enters `REGISTERED`, with `consent_on_file` false. A recipient advances to `ACTIVE` on their first signed consent, and `SUSPENDED` is the alternate off-ramp.

Before any vials may be reserved against a given donor, the recipient must have a signed consent on file for that donor. A consent is drafted — by a `Recipient` or a `CatalogManager` — by naming the `recipient_id`, the `donor_id`, and `acknowledges_open_id`, the recipient's acknowledgement of the donor's open-identity disclosure terms. A drafted consent enters `DRAFT`.

Signing is a `Recipient` action that advances the consent `DRAFT` → `SIGNED`. It requires that the consent be in `DRAFT`, that `acknowledges_open_id` is true, and that the referenced donor's status is `APPROVED` or `ACTIVE`. A sign attempt where `acknowledges_open_id` is false is rejected with `ERR_CONSENT_NOT_ACKNOWLEDGED`. On signing, the recipient's `consent_on_file` becomes true, and on the recipient's first signed consent the recipient's status advances to `ACTIVE`.

A consent may be revoked by a `Recipient`, advancing it `SIGNED` → `REVOKED` (terminal). Revocation requires that the consent be `SIGNED` and that the same recipient-and-donor pairing has no vial reservation in `HELD`, `CONFIRMED`, or `SHIPPED`; if such an active reservation exists, the revocation is blocked with `ERR_ACTIVE_RESERVATION_EXISTS`. After a successful revocation, the recipient's `consent_on_file` is recomputed and becomes false only if the recipient has no other consent still in `SIGNED`.

### 3.4. Vial Reservation Lifecycle and Reservation-Time Guards

The core allocation act is a vial hold. A `CatalogManager` or a `Recipient` places one by naming the `recipient_id`, the `inventory_id` of the target donor inventory lot, the `vial_count` requested (a positive integer), and `expected_inventory_version`. The reservation records the resolved `donor_id` of the lot and computes a `hold_expiry`; a newly created reservation enters `HELD`.

Reservation creation is the most heavily guarded operation in the system, and its business checks are evaluated in a fixed order. First, the recipient must hold a `SIGNED` `RecipientConsent` for the pairing of that recipient and the donor owning the target inventory; absent such a consent, the create is rejected with `ERR_CONSENT_MISSING`. Second, the donor must not have reached its family limit: if the donor's `is_family_limit_reached` is true at create time, the create is rejected with `ERR_FAMILY_LIMIT_REACHED`. Third, the inventory must be listable — its `hold_status` must be `OPEN`, its specimen must be `RELEASED`, and its `is_listed` must be true; a create against a lot that is `FROZEN`, whose specimen is not `RELEASED`, or that is otherwise unlisted is rejected with `ERR_INVENTORY_NOT_LISTED`. Fourth, the requested `vial_count` must not exceed the lot's `available_vials`; a request for more than are available is rejected with `ERR_INSUFFICIENT_VIALS`. Finally, the optimistic-concurrency guard of §2.7 applies: `expected_inventory_version` must equal the lot's current `version`, or the create is rejected with `ERR_STALE_INVENTORY_VERSION`. On a successful hold, the reservation is created in `HELD`, its `hold_expiry` is set, the donor inventory lot's `version` is incremented by one, and the lot's `reserved_vials`, `available_vials`, and `is_listed` are recomputed.

Confirmation is a `CatalogManager` action advancing the reservation `HELD` → `CONFIRMED`. It requires that the reservation be `HELD`, that the current logical time is still before the reservation's `hold_expiry`, and that the owning inventory lot's `hold_status` is `OPEN`. Confirmation does not change any vial counts — a confirmed reservation continues to be counted in the lot's `reserved_vials` — and it does not yet create a storage account.

A reservation may be cancelled by a `CatalogManager` or a `Recipient`, either from `HELD` → `CANCELLED` or from `CONFIRMED` → `CANCELLED`, and cancellations also arise from the system cascades of §3.2. Cancelling a `HELD` reservation subtracts its `vial_count` from the lot's `reserved_vials` and recomputes `available_vials` and `is_listed`. Cancelling a `CONFIRMED` reservation does the same and, additionally, if a linked shipment exists in `PREPARING` or `DISPATCHED`, drives that shipment to `CANCELLED`.

A held reservation whose hold window has passed may be swept to expiry by a `CatalogManager`, advancing it `HELD` → `EXPIRED`. This requires that the reservation be `HELD` and that the current logical time has reached or passed its `hold_expiry`. Expiry subtracts the reservation's `vial_count` from the lot's `reserved_vials` and recomputes `available_vials` and `is_listed`. The hold window itself is defined in §3.5.

### 3.5. Inventory Availability, Family Limits, and Catalog Listing

An inventory lot maintains two availability views over the same underlying reservations, and they differ in how they treat pending holds. The lot's `reserved_vials` is the sum of `vial_count` over every reservation in `HELD` or `CONFIRMED` on the lot; its `shipped_vials` is the sum of `vial_count` over every reservation in `SHIPPED` on the lot. The booking view, `available_vials`, is the lot's `total_vials` minus `reserved_vials` minus `shipped_vials` — a pessimistic figure in which even an unconfirmed `HELD` hold reduces what a new reservation may claim, and it is this figure that the availability guard of §3.4 compares against a requested `vial_count`. The settlement view, `committed_available_vials`, is instead the lot's `total_vials` minus the sum of `vial_count` over reservations in `CONFIRMED` or `SHIPPED` only; it deliberately excludes `HELD` holds, treating them as not yet firmly committed, and therefore yields a value that is larger than `available_vials` whenever any `HELD` hold exists on the lot. These figures are recomputed on every reservation create, confirm, cancel, and expire, on shipment dispatch, and on specimen discard.

The hold window on a reservation is fixed in duration. A reservation's `hold_expiry` is its `created_at` advanced by the hold time-to-live of five days (that is, `HOLD_TTL_DAYS` is 5); a `HELD` reservation whose `hold_expiry` has been reached or passed is eligible for expiry sweeping.

A donor's family limit gates the catalog. The donor's `reported_family_count` is the number of distinct recipients (`recipient_id`) that have at least one sibling-registry entry in `CONFIRMED` status for that donor; entries still `PENDING` or already `REJECTED` are not counted. The donor's `is_family_limit_reached` flag is true exactly when `reported_family_count` is greater than or equal to `family_limit` — note that reaching the limit exactly, not merely exceeding it, closes the donor. When the limit is reached, every one of the donor's inventory lots is delisted (its `is_listed` recomputed to false), and a new hold is refused with `ERR_FAMILY_LIMIT_REACHED` per §3.4.

An inventory lot is catalog-listed (`is_listed` true) precisely when all of the following hold together: its specimen is `RELEASED`, its donor is `ACTIVE`, the donor's `is_family_limit_reached` is false, its `hold_status` is `OPEN`, and its `available_vials` is greater than 0. Any change to a contributing input — a release, a deferral freeze, a limit breach, or a change in availability — triggers a recomputation of this flag.

### 3.6. Shipment and Fulfillment

Once a reservation is `CONFIRMED`, a `LabTech` prepares a shipment by naming the `reservation_id`, the destination fertility-clinic `clinic_address`, and the `ln2_dewar_serial` of the dry-shipper dewar being dispatched. The shipment records the resolved `recipient_id` and enters `PREPARING`.

Dispatch is a `LabTech` action advancing the shipment `PREPARING` → `DISPATCHED`. It requires that the shipment be `PREPARING`, that its linked reservation be `CONFIRMED`, and that the owning inventory lot's `hold_status` be `OPEN`. On dispatch, the shipment's `dispatched_at` is set to the current UTC instant, and the linked reservation is driven `CONFIRMED` → `SHIPPED`. That reservation transition moves the reservation's `vial_count` from the lot's `reserved_vials` into `shipped_vials` (leaving `available_vials` unchanged, since the vials were already committed), creates a `StorageAccount` in `ACTIVE` status with `stored_vials` equal to the reservation's `vial_count` and `period_start` at the current UTC instant, and issues the account's first `StorageInvoice` at `period_index` 0 under the `RENEWAL` billing mode for a full first period.

Delivery is a `LabTech` action advancing the shipment `DISPATCHED` → `DELIVERED`, requiring only that the shipment be `DISPATCHED`; the reservation remains `SHIPPED`, which is terminal. A shipment may also be cancelled by the system cascades of §3.2 and §3.4: a shipment in `PREPARING` may be driven to `CANCELLED`, and a shipment in `DISPATCHED` may be driven to `CANCELLED`, in each case doing nothing beyond marking the shipment `CANCELLED`.

### 3.7. Storage Billing, Renewal, and Lapse

Each shipped reservation gives rise to a `StorageAccount` under which the recipient's vials are billed for long-term LN2 storage. The account carries the `recipient_id`, the `reservation_id`, the `stored_vials` under management, a system-set `period_start` marking the start of the current billing period, and a computed `paid_through` marking the end of the period covered by the most recent paid invoice. An account is `ACTIVE`, may fall to `LAPSED`, and may be `CLOSED`.

Every `StorageInvoice` carries the `storage_account_id`, a 0-based sequential `period_index` identifying the period it covers, a `billing_mode` of `RENEWAL` or `LAPSE`, and a computed `amount_cents`. An invoice is `ISSUED`, then either `PAID` or `VOID`. The charge for one full billing period is the account's `stored_vials` multiplied by the annual per-vial rate of 42000 cents (that is, `ANNUAL_RATE_CENTS_PER_VIAL`, equivalent to $420.00 per vial per full period), where a full period is 365 days (`BILLING_PERIOD_DAYS`). Call this full-period figure the base charge.

The two billing modes compute `amount_cents` differently from the same base. Under the `RENEWAL` mode, the charge is prorated to the moment of renewal. Let the elapsed whole days be the number of days from the account's `period_start` to the renewal instant, taken as a floor to whole days; let the remaining days be 365 minus those elapsed days. The renewal charge is the base charge multiplied by the remaining days and divided by 365, rounded half-up to whole cents. The first invoice at `period_index` 0, issued at dispatch, is a special case of the `RENEWAL` mode covering a full period — its remaining days equal the full 365, so its charge equals the base exactly. Under the `LAPSE` mode, no proration applies: the charge is simply the base for the full period regardless of how many days have elapsed. Because the `RENEWAL` proration factor never exceeds 1, the two modes computed over identical data yield an equal amount only when no whole day has elapsed; once at least one whole day has elapsed, the `RENEWAL` charge is strictly smaller than the `LAPSE` charge.

A `BillingClerk` may early-renew an active account, which issues a `RENEWAL` invoice for the remaining days of the current period computed as above. A `BillingClerk` may also assess a lapse, advancing the account `ACTIVE` → `LAPSED`. Assessment requires that the account be `ACTIVE` and that the current logical time has reached or passed `paid_through` plus the grace period of 30 days (`GRACE_DAYS`); an assessment attempted before the grace period has elapsed — the current instant still earlier than `paid_through` plus 30 days — is rejected with `ERR_GRACE_NOT_ELAPSED`. A successful assessment issues a `LAPSE` invoice for the full unpaid period.

Paying an invoice is a `BillingClerk` action that marks the invoice `ISSUED` → `PAID` and advances the account's `paid_through` by one full 365-day billing period. When the invoice being paid is the `LAPSE` invoice on a `LAPSED` account (the account is `LAPSED`, the invoice is `ISSUED`, and its `billing_mode` is `LAPSE`), paying it also advances `paid_through` by one billing period and restores the account `LAPSED` → `ACTIVE`. A `BillingClerk` may close an `ACTIVE` account, advancing it `ACTIVE` → `CLOSED` and voiding every `ISSUED` invoice on that account.

### 3.8. Sibling Registry and Family-Limit Enforcement

The sibling registry records live births attributed to a donor across recipient families and is the mechanism by which a donor's family limit is enforced. A `ComplianceOfficer` or a `Recipient` reports a birth by naming the `donor_id`, the `recipient_id`, and the `birth_reported_date`. A new entry enters `PENDING`.

A `ComplianceOfficer` confirms an entry, advancing it `PENDING` → `CONFIRMED`. Confirmation requires that the entry be `PENDING` and that the recipient has at least one `SHIPPED` vial reservation for that donor; a confirmation attempted without such a shipped reservation is rejected with `ERR_REGISTRY_NO_SHIPMENT`. On confirmation, the donor's `reported_family_count` is recomputed as the count of distinct `recipient_id` having a `CONFIRMED` entry for that donor, and the donor's `is_family_limit_reached` is recomputed (true when that count reaches or exceeds `family_limit`); if the limit is now reached, every one of the donor's inventory lots has its `is_listed` recomputed to false. Alternatively, a `ComplianceOfficer` may reject an entry, advancing it `PENDING` → `REJECTED` with no further effect. Both `CONFIRMED` and `REJECTED` are terminal.

### 3.9. Collection Rooms and Dewar Maintenance Scheduling

Two scheduling resources protect physical resources from double-booking, and they use deliberately different overlap semantics.

A `LabTech` books a collection-room window as a `CollectionAppointment` by naming the `donor_id`, the `room_code` of the room being occupied, the `window_start` (inclusive UTC start), and the `window_end` (exclusive UTC end). Room windows use half-open interval semantics with no buffer: a new appointment conflicts with an existing `BOOKED` appointment on the same `room_code` when the new window's start falls before the existing window's end and the existing window's start falls before the new window's end. Two windows that merely touch at an endpoint — where one's end equals the other's start — do not conflict. A conflicting booking is rejected with `ERR_ROOM_WINDOW_CONFLICT`. A booked appointment may be completed by a `LabTech` (`BOOKED` → `COMPLETED`, no side effect) or cancelled by a `LabTech` (`BOOKED` → `CANCELLED`), where cancellation frees the room window so a later booking may overlap the vacated time.

A `LabTech` schedules an LN2 dewar service as a `DewarMaintenanceWindow` by naming the `dewar_code` being serviced (which matches an inventory lot's `dewar_code`), the `service_start` (inclusive UTC start), and the `service_end` (inclusive UTC end). Dewar windows use closed-interval semantics with a symmetric buffer of 24 hours applied to both ends (`SETTLE_BUFFER_HOURS` is 24). A new window conflicts with an existing `SCHEDULED` window on the same `dewar_code` when the new window's start minus the 24-hour buffer is at or before the existing window's end, and the existing window's start is at or before the new window's end plus the 24-hour buffer — so that windows which touch, or fall within a day of each other on either side, do conflict. A conflicting schedule is rejected with `ERR_DEWAR_WINDOW_CONFLICT`. A scheduled window may be completed by a `LabTech` (`SCHEDULED` → `DONE`, no side effect) or cancelled by a `LabTech` (`SCHEDULED` → `CANCELLED`), where cancellation frees the dewar window so a later window may overlap the vacated time.

### 3.10. Regulatory Reporting

A `ComplianceOfficer` files a regulatory report by naming the `donor_id`, the `report_type` — one of `ADVERSE_REACTION`, `FDA_ANNUAL`, or `GENETIC_UPDATE` — and the `as_of` UTC instant the report summarizes. Filing snapshots two figures onto the report: `total_families_at_report`, which captures the donor's `reported_family_count` as of the report, and `total_vials_shipped_at_report`, which is the sum of `vial_count` over that donor's reservations in `SHIPPED` status. A filed report enters `FILED`, which is terminal.

### 3.11. Logical Clock

Because quarantine release, hold expiry, lapse assessment, and window overlap all depend on time, the platform runs on a settable logical clock rather than wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any clock-setting call it holds this default and never falls back to real wall-clock time. Any role may advance the clock to a supplied `to_iso8601` instant; doing so sets the server's current UTC to that instant and is the mechanism by which sweep-style operations (reservation expiry and lapse assessment) are driven in tests.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify or transition an existing resource, including the clock-setting utility, return `200 OK`. Every request must carry the `X-User-ID` and `X-User-Role` headers described in §2.1; the request and response bodies for each operation are reconstructed from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/donors` | Register a donor applicant | ScreeningOfficer |
| GET | `/donors/{id}` | Get a donor | ScreeningOfficer, CatalogManager, ComplianceOfficer, Recipient, LabTech, BillingClerk |
| GET | `/donors` | List/catalog donors (paginated, filterable) | ScreeningOfficer, CatalogManager, ComplianceOfficer, Recipient, LabTech, BillingClerk |
| POST | `/screening-applications` | Submit a screening application for a donor | ScreeningOfficer |
| GET | `/screening-applications/{id}` | Get an application | ScreeningOfficer, ComplianceOfficer |
| GET | `/screening-applications` | List applications (filter by donor_id) | ScreeningOfficer, ComplianceOfficer |
| POST | `/screening-applications/{id}/start-review` | Begin review | ScreeningOfficer |
| POST | `/screening-applications/{id}/approve` | Approve donor screening | ScreeningOfficer |
| POST | `/screening-applications/{id}/defer` | Defer (reject) donor screening | ScreeningOfficer |
| POST | `/specimens` | Record a specimen collection | LabTech |
| GET | `/specimens/{id}` | Get a specimen | LabTech, ComplianceOfficer, CatalogManager |
| GET | `/specimens` | List specimens (filter by donor_id) | LabTech, ComplianceOfficer, CatalogManager |
| POST | `/specimens/{id}/begin-quarantine` | Move specimen to quarantine and mint inventory lot | LabTech |
| POST | `/specimens/{id}/release-quarantine` | Release specimen from 180-day quarantine | ComplianceOfficer |
| POST | `/specimens/{id}/discard` | Discard a specimen | ComplianceOfficer |
| GET | `/donor-inventories/{id}` | Get an inventory lot | CatalogManager, LabTech, ComplianceOfficer, Recipient |
| GET | `/donor-inventories` | List inventory lots (filter by specimen_id or donor_id) | CatalogManager, LabTech, ComplianceOfficer, Recipient |
| POST | `/recipients` | Register a recipient family | CatalogManager, Recipient |
| GET | `/recipients/{id}` | Get a recipient | CatalogManager, Recipient, ComplianceOfficer, BillingClerk |
| GET | `/recipients` | List recipients | CatalogManager, ComplianceOfficer, BillingClerk |
| POST | `/recipient-consents` | Draft a recipient consent | Recipient, CatalogManager |
| GET | `/recipient-consents/{id}` | Get a consent | Recipient, CatalogManager, ComplianceOfficer |
| GET | `/recipient-consents` | List consents (filter by recipient_id or donor_id) | Recipient, CatalogManager, ComplianceOfficer |
| POST | `/recipient-consents/{id}/sign` | Sign a consent | Recipient |
| POST | `/recipient-consents/{id}/revoke` | Revoke a consent | Recipient |
| POST | `/vial-reservations` | Place a vial hold against an inventory lot | CatalogManager, Recipient |
| GET | `/vial-reservations/{id}` | Get a reservation | CatalogManager, Recipient, LabTech, ComplianceOfficer, BillingClerk |
| GET | `/vial-reservations` | List reservations (filter by recipient_id, inventory_id, donor_id) | CatalogManager, Recipient, LabTech, ComplianceOfficer, BillingClerk |
| POST | `/vial-reservations/{id}/confirm` | Confirm a held reservation | CatalogManager |
| POST | `/vial-reservations/{id}/cancel` | Cancel a held/confirmed reservation | CatalogManager, Recipient |
| POST | `/vial-reservations/{id}/expire` | Sweep-expire a held reservation past hold_expiry | CatalogManager |
| POST | `/shipments` | Prepare a shipment for a confirmed reservation | LabTech |
| GET | `/shipments/{id}` | Get a shipment | LabTech, ComplianceOfficer, Recipient |
| GET | `/shipments` | List shipments (filter by reservation_id or recipient_id) | LabTech, ComplianceOfficer, Recipient |
| POST | `/shipments/{id}/dispatch` | Dispatch the LN2 dewar; ships the reservation | LabTech |
| POST | `/shipments/{id}/deliver` | Mark a shipment delivered | LabTech |
| GET | `/storage-accounts/{id}` | Get a storage account | BillingClerk, Recipient |
| GET | `/storage-accounts` | List storage accounts (filter by recipient_id or reservation_id) | BillingClerk, Recipient |
| POST | `/storage-accounts/{id}/assess-lapse` | Assess a lapsed billing period past grace | BillingClerk |
| POST | `/storage-accounts/{id}/renew` | Early-renew: prorate and issue a RENEWAL invoice | BillingClerk |
| POST | `/storage-accounts/{id}/close` | Close a storage account | BillingClerk |
| GET | `/storage-invoices/{id}` | Get an invoice | BillingClerk, Recipient |
| GET | `/storage-invoices` | List invoices (filter by storage_account_id) | BillingClerk, Recipient |
| POST | `/storage-invoices/{id}/pay` | Pay an issued invoice | BillingClerk |
| POST | `/sibling-registry` | Report a live birth into the sibling registry | ComplianceOfficer, Recipient |
| GET | `/sibling-registry/{id}` | Get a registry entry | ComplianceOfficer, Recipient |
| GET | `/sibling-registry` | List registry entries (filter by donor_id or recipient_id) | ComplianceOfficer, Recipient |
| POST | `/sibling-registry/{id}/confirm` | Confirm a registry entry (counts toward family-limit) | ComplianceOfficer |
| POST | `/sibling-registry/{id}/reject` | Reject a registry entry | ComplianceOfficer |
| POST | `/collection-appointments` | Book a collection-room window | LabTech |
| GET | `/collection-appointments/{id}` | Get an appointment | LabTech, ScreeningOfficer |
| GET | `/collection-appointments` | List appointments (filter by donor_id or room_code) | LabTech, ScreeningOfficer |
| POST | `/collection-appointments/{id}/complete` | Complete an appointment | LabTech |
| POST | `/collection-appointments/{id}/cancel` | Cancel an appointment | LabTech |
| POST | `/dewar-maintenance-windows` | Schedule an LN2 dewar maintenance window | LabTech |
| GET | `/dewar-maintenance-windows/{id}` | Get a maintenance window | LabTech, ComplianceOfficer |
| GET | `/dewar-maintenance-windows` | List maintenance windows (filter by dewar_code) | LabTech, ComplianceOfficer |
| POST | `/dewar-maintenance-windows/{id}/complete` | Complete maintenance | LabTech |
| POST | `/dewar-maintenance-windows/{id}/cancel` | Cancel maintenance | LabTech |
| POST | `/regulatory-reports` | File a regulatory report snapshot | ComplianceOfficer |
| GET | `/regulatory-reports/{id}` | Get a report | ComplianceOfficer |
| GET | `/regulatory-reports` | List reports (filter by donor_id) | ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ScreeningOfficer, LabTech, CatalogManager, ComplianceOfficer, BillingClerk, Recipient |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_RETEST_NOT_NEGATIVE` | 422 Unprocessable Entity |
| `ERR_QUARANTINE_NOT_ELAPSED` | 422 Unprocessable Entity |
| `ERR_FDA_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_GENETIC_SCREENING_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_CONSENT_MISSING` | 422 Unprocessable Entity |
| `ERR_FAMILY_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_INVENTORY_NOT_LISTED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_VIALS` | 422 Unprocessable Entity |
| `ERR_STALE_INVENTORY_VERSION` | 412 Precondition Failed |
| `ERR_REGISTRY_NO_SHIPMENT` | 422 Unprocessable Entity |
| `ERR_CONSENT_NOT_ACKNOWLEDGED` | 422 Unprocessable Entity |
| `ERR_ACTIVE_RESERVATION_EXISTS` | 409 Conflict |
| `ERR_GRACE_NOT_ELAPSED` | 422 Unprocessable Entity |
| `ERR_ROOM_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DEWAR_WINDOW_CONFLICT` | 409 Conflict |
