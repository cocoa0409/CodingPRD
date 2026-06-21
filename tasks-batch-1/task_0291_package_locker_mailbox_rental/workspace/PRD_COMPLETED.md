# Package Locker & Mailbox Rental API — Product Requirements Document

## 1. Introduction

This document specifies the Package Locker & Mailbox Rental API, the system of record behind a retail mail-and-parcel facility — the kind of storefront that rents private mailboxes, holds incoming parcels in lockers, and forwards or scans mail on a customer's behalf. The product exists to replace the brittle paper logbooks and spreadsheets that such facilities typically run on, where a misplaced Form 1583, an unbilled overstay, or a locker double-booked between two carriers quietly erodes both compliance and revenue.

The API governs the full operational arc of a facility: physical inventory (lockers sized for parcels and PO-style mailboxes sized for letter mail), the rental relationship between a customer and a mailbox, the federally mandated recipient authorization (USPS Form 1583) that must be verified before a box may be used, and the day-to-day flow of packages and letter mail through receipt, notification, pickup, forwarding, scanning, return, and ultimately abandonment. Layered on top is a billing subsystem — a single open invoice per rental, an append-only ledger of charges and credits, optional autopay, and proration math on early closure.

Because money, calendar time, and physical occupancy all move together, the system is built around immediate consistency: a state change on a rental cascades to its mailbox, its packages, its mail, and its forwarding requests within the same operation, and every fee is pinned at a well-defined moment so that two readers of the same invoice never disagree. A facility-local logical clock drives all time-dependent behavior — overstay accrual, abandonment, and balance-driven suspension — so that the system's notion of "now" is explicit, advanceable, and reproducible rather than tied to wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint. Where a business workflow in Section 3 refers to "the standard envelope," "the facility clock," or "the version check," the precise definition lives here.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. The system recognizes exactly three roles, spelled precisely as `FacilityOperator`, `Customer`, and `ComplianceOfficer`. A request missing either header, or carrying an `X-User-Role` value that is not one of these three, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request that is well-authenticated but attempts an operation the role is not permitted to perform — or a `Customer` reaching for a resource it does not own — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The three roles partition responsibility along business lines. A `FacilityOperator` is front-desk and back-office staff: they own the facility record, locker and mailbox inventory, package receiving, the logical-clock sweeps, and billing capture. A `Customer` is the renter — they act on their own rentals, forms, packages, mail, forwarding requests, and payments. A `ComplianceOfficer` reviews recipient authorizations: they alone verify or reject a Form 1583, and they may also place a customer on a compliance hold.

The two operator-style roles carry no persisted identity. When `X-User-Role` is `FacilityOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and log it but never compares it to any entity's `id`. The same holds when `X-User-Role` is `ComplianceOfficer`: `X-User-ID` is an opaque reviewer identifier, recorded if useful but never matched against a stored row. The `Customer` role, by contrast, is entity-backed. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's customer chain back to `X-User-ID`. A rental agreement is owned by the customer named in its `customer_id`; a Form 1583 by its `customer_id`; a package, mail item, forwarding request, invoice, or payment is owned by whichever customer sits at the head of its rental-agreement chain. When a `Customer` targets a resource that resolves to a different customer, the request fails with `ERR_FORBIDDEN`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may not be smaller than 1, and may not exceed 100. The `offset` parameter is the number of items to skip from the front of the result and defaults to 0.

Unless an endpoint states otherwise, every list is sorted by the resource's `created_at` timestamp in ascending order. List responses populate the `limit`, `offset`, `total_count`, and `has_more` fields in the envelope's `meta` object, where `total_count` reflects the full count matching the filters before pagination and `has_more` indicates whether further items remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id` formatted as a UUID with no type prefix — the `id` is identity only and is never reused to encode a foreign key. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC instant with three fractional digits, set once at creation.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed on every mutation, including mutations that arrive indirectly through a cascade rather than a direct request. The `version` field starts at 1 at creation and increases by exactly 1 on every mutation; it is the basis for the optimistic-concurrency checks described in §2.5. These common fields — `updated_at` and `version` — are present on `Facility`, `LockerUnit`, `MailboxUnit`, `Customer`, `Form1583`, `RentalAgreement`, `Package`, `MailItem`, `ForwardingRequest`, `Invoice`, and `Payment`.

Two record types are deliberately append-only and therefore carry only `id` and `created_at`, with no `updated_at` and no `version`: an `AuthorizedRecipient`, which is an immutable line on a Form 1583, and a `LedgerEntry`, which once posted is never altered. Treat the absence of `updated_at`/`version` on these two as intentional, not as an omission to be filled in.

Note that two of the timestamp-typed fields in this domain are measured against the facility's own logical clock rather than against `created_at`. Specifically, the moment a recipient is notified and the moment a package, agreement, or form reaches a clock-driven milestone are stamped from the facility's `current_utc` (see §2.6), not from server wall-clock time. The system-managed `created_at`/`updated_at` audit fields remain real ISO 8601 UTC instants.

### 2.5. Optimistic Concurrency Control on Guarded Writes

Two operations in this system are guarded by optimistic concurrency control, and only these two. Each requires the client to declare the `version` it last observed on the parent resource, and each rejects the write if that declared version no longer matches the parent's current `version`.

Renewing a rental agreement is one such guarded write. The request must carry `expected_rental_agreement_version`, and that value must equal the target `RentalAgreement`'s current `version`. If another writer has advanced the agreement's version since the client last read it — for example, a prior renewal that already extended the term and posted another rental charge — the renewal is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client that holds a superseded view from double-extending the term off stale data.

Picking up a package is the other guarded write. The request must carry `expected_package_version`, and that value must equal the target `Package`'s current `version`. A notification (which advances the package version) or a clock-driven provisional overstay recompute (which also advances it) can move the version after the client's last read; a pickup still carrying the pre-advance version is operating on a superseded view of the package's fee and state and is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field. Operations not named here perform their mutation without an OCC check.

### 2.6. The Facility Logical Clock and Scheduled Sweeps

Each `Facility` owns a logical clock exposed as its `current_utc` field. A freshly created facility starts with `current_utc` set to `1970-01-01T00:00:00.000Z`, and the clock advances only through the dedicated clock-advance capability, never as a side effect of ordinary traffic. The advance request supplies a target instant as `to_iso8601`; the new instant must be greater than or equal to the facility's prior `current_utc`, and a request that would move the clock backward is rejected with `ERR_INVALID_CLOCK` (HTTP 422). On success the facility's `current_utc` is set to `to_iso8601`.

Advancing the clock is also when the system performs its deferred bookkeeping, in a single sweep. Every `NOTIFIED` package has its provisional overstay fee recomputed against the new clock (see §3.5). Any package still `RECEIVED` or `NOTIFIED` whose notification is now far enough in the past becomes abandoned; any `ACTIVE` agreement whose outstanding balance has grown past the suspension threshold is suspended; and any agreement whose term has lapsed past its abandonment grace with money still owed is abandoned. The precise day counts and thresholds, and the cascades each sweep triggers, are given in §3 alongside the workflows they belong to. Because these are calendar-day computations, all day arithmetic for overstay, proration, abandonment, and suspension is performed in the facility's `time_zone` (an IANA zone, defaulting to `UTC`), not in raw UTC.

### 2.7. Cascading State and Hierarchical Consistency

The rental sits at the top of a small hierarchy — a mailbox it occupies, the packages and mail items received against it, and the forwarding requests raised on that mail. When a rental changes state, the system propagates the consequences across that hierarchy within the same operation, rather than leaving children stranded in contradictory states. Suspending a rental places its open forwarding requests on hold; reactivating releases them; closing or abandoning a rental frees the mailbox, resolves its stored mail, and cancels outstanding forwarding work. Each of these cascades is spelled out in the relevant workflow in §3.

Every resource touched by a cascade is itself mutated: its `updated_at` is refreshed and, where it carries one, its `version` is incremented, exactly as if it had been the direct target of a request. A parent whose computed fields shift as a result — a facility's locker counts, an invoice's totals — is likewise re-derived immediately. The guiding rule is that after any single API call returns, no derived field and no dependent state is left waiting for a later reconciliation.

### 2.8. Nested Resource Retrieval and Reference Validation

Several paths address a child through its parent — recipients under a form, ledger entries under an invoice. For any such path the system validates identifiers left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not resolve, before considering anything to its right. The same ordering governs request bodies: any foreign key supplied in a body — a `facility_id`, a `customer_id`, a `mailbox_unit_id`, a `form_1583_id`, a `rental_agreement_id`, a `mail_item_id`, an `invoice_id`, a `locker_unit_id` — must reference an existing row, and a dangling reference is `ERR_NOT_FOUND`. Existence is checked ahead of any state or business rule, so a request against a missing resource never surfaces as a state conflict.

### 2.9. Monetary Amounts, Counts, and Rounding

Every monetary value in the system is an integer number of cents; there are no fractional-cent representations and no floating-point money. Fields such as `monthly_fee_cents`, `oversize_fee_cents`, `overstay_fee_cents`, `fee_cents`, `amount_cents`, `charges_total_cents`, `credits_total_cents`, `payments_total_cents`, and `balance_cents` are all whole cents.

Where a calculation involves division — proration is the only such case — the division is performed first and the result is rounded to a whole number of cents using the round-half-up convention (a result whose fractional part is exactly one half rounds away from zero, upward). Fee calculations that count "buckets" of oversize round the bucket count up to the next whole bucket (ceiling) before multiplying by a rate. Invoice totals are pure sums of already-integer line items: each `LedgerEntry` and each `Payment` is an integer-cent amount, and the invoice sums those integers directly without ever re-rounding a running subtotal. Count fields — `total_locker_count`, `available_locker_count`, `submission_count`, `renewal_count` — are non-negative integers, and the available-locker count in particular is never allowed to fall below zero.

### 2.10. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role-and-ownership authorization (`ERR_FORBIDDEN`), then existence of every path id and every body foreign key (`ERR_NOT_FOUND`), then well-formedness of the request body (`ERR_INVALID_REQUEST`). Only after those four gates does the system evaluate state legality (`ERR_INVALID_STATE`), then the optimistic-concurrency version match on the two guarded writes (`ERR_STALE_VERSION`), and finally the domain-specific business rules — the activation gate, the pickup code, mailbox occupancy, locker availability, unresolved packages, the active-required gate, and uniqueness. In short: authentication, then authorization, then existence, then body validity, then state, then version, then business rules. A body that is well-formed but names a non-existent foreign key still fails existence first; a transition requested on a resource in the wrong state fails on state before any version or business check is consulted.

A request body is well-formed when every required field is present, every enum value is one of its declared members, every integer respects its declared minimum, and — for a forwarding request whose `kind` is `FORWARD` — a `destination_address` is supplied. A body that violates any of these is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Facility Setup and Physical Inventory

A `FacilityOperator` stands up a facility by supplying its `name` and, optionally, a `time_zone`; when the time zone is omitted it defaults to `UTC`. A new facility opens with its logical clock at the epoch, its `total_locker_count` and `available_locker_count` at zero, and its `version` at 1. The two locker counts are always derived, never set directly: `total_locker_count` is the number of locker units under the facility, and `available_locker_count` is the number of those whose `status` is `AVAILABLE`. Both are recomputed whenever a locker is created or changes status, and a read of the facility returns the current values.

Lockers hold parcels. An operator creates a `LockerUnit` by giving its `facility_id`, a physical `label` that must be unique within the facility, and a `size_tier` of `SMALL`, `MEDIUM`, `LARGE`, or `XL`. A new locker is `AVAILABLE`. Its `status` thereafter moves among `AVAILABLE`, `OCCUPIED`, and `OUT_OF_SERVICE`: it becomes `OCCUPIED` when a package is assigned into it and returns to `AVAILABLE` when that package leaves. A locker carries a convenience back-reference, `current_package_id`, holding the `id` of the single package currently occupying it, which is null whenever the locker is `AVAILABLE` or `OUT_OF_SERVICE`; the authoritative link is `Package.locker_unit_id`, and the packages occupying a given locker are discoverable by filtering packages on `locker_unit_id`. An operator may take an `AVAILABLE` locker out of service, transitioning `AVAILABLE → OUT_OF_SERVICE` and decrementing `available_locker_count` by one; restoring it transitions `OUT_OF_SERVICE → AVAILABLE` and increments the count by one. Taking out of service or restoring from any other state is an illegal transition and is rejected with `ERR_INVALID_STATE`. Creating a second locker with a `label` already used in the facility is rejected with `ERR_DUPLICATE`.

Mailboxes hold letter mail and are what customers rent. An operator creates a `MailboxUnit` with its `facility_id`, a `box_number` unique within the facility, a `size_tier` of `SMALL`, `MEDIUM`, or `LARGE`, and a `monthly_fee_cents` list price (at least zero) for that box size. A new mailbox is `VACANT`; its `status` ranges over `VACANT`, `RENTED`, and `OUT_OF_SERVICE`. Renting drives `VACANT → RENTED` and closing or abandoning the rental drives it back to `VACANT`, both as system cascades described in §3.3. An operator may take a `VACANT` mailbox out of service (`VACANT → OUT_OF_SERVICE`) and later restore it (`OUT_OF_SERVICE → VACANT`); attempting to take a mailbox out of service while it is `RENTED`, or to restore one that is not `OUT_OF_SERVICE`, is rejected with `ERR_MAILBOX_NOT_VACANT`. A duplicate `box_number` within the facility is rejected with `ERR_DUPLICATE`.

### 3.2. Customers and Form 1583 Authorization

Anyone renting must first exist as a `Customer` and must clear federal recipient authorization before a box can be used. A customer is registered with a `facility_id`, a `full_name`, an `email` unique within the facility, and a `phone`; a `Customer` begins `ACTIVE`, and a duplicate `email` in the same facility is rejected with `ERR_DUPLICATE`. A customer's `status` is either `ACTIVE` or `SUSPENDED`; an operator or a compliance officer may place a customer on a `ACTIVE → SUSPENDED` hold for fraud or compliance reasons. Suspending a customer that is not `ACTIVE` (already `SUSPENDED`) is an illegal transition and is rejected with `ERR_INVALID_STATE`. When a customer registers themselves, `X-User-ID` becomes that customer's `id`.

Recipient authorization is captured as a **Form 1583**. A draft is created against a `customer_id` and `facility_id`, recording the photo identification shown — `primary_id_type` of `PASSPORT`, `DRIVERS_LICENSE`, or `STATE_ID` — and the secondary address proof, `address_proof_type` of `LEASE`, `UTILITY_BILL`, or `VEHICLE_REG`. A fresh form is in `DRAFT` with `submission_count` at zero. The form's `status` traverses `DRAFT`, `SUBMITTED`, `VERIFIED`, and `REJECTED`, and `VERIFIED` is the single terminal state.

Before a form can be submitted, at least one authorized recipient must be listed on it. Each `AuthorizedRecipient` is an immutable line carrying a `recipient_name` and a `relationship` of `SELF`, `FAMILY`, `BUSINESS`, or `MINOR`, attached to the form through its `form_1583_id`. Submitting a form requires that it be in `DRAFT` (or in `REJECTED`, for a resubmission) and that at least one recipient exist on it; a submit with no recipients is rejected with `ERR_NO_RECIPIENTS`, and a submit from any state other than `DRAFT` or `REJECTED` is rejected as an illegal `ERR_INVALID_STATE`. Each successful submission drives the form to `SUBMITTED` and increments `submission_count` by one. When the submission comes out of `REJECTED`, it additionally clears `rejection_reason` back to null.

A `ComplianceOfficer` adjudicates a `SUBMITTED` form. Verifying it transitions `SUBMITTED → VERIFIED` and stamps `verified_at` with the facility's current clock value; verifying anything not in `SUBMITTED` is `ERR_INVALID_STATE`. Rejecting it transitions `SUBMITTED → REJECTED` and records the supplied `rejection_reason` on the form. A rejected form is not dead — the customer may add or amend recipients and resubmit, which loops `REJECTED → SUBMITTED` and clears the prior `rejection_reason`. While a form sits in `REJECTED`, any rental agreement still pointing at it through its `form_1583_id` and waiting in `PENDING_AUTH` remains blocked from activation.

### 3.3. The Rental Agreement Lifecycle

A rental ties a customer to a mailbox under an authorized form. A `RentalAgreement` is created with a `facility_id`, a `customer_id`, a `mailbox_unit_id`, a `form_1583_id`, a `term_months` of at least 1, and an optional `autopay_enabled` flag defaulting to false. At creation the agreement snapshots the mailbox's list price into its own `monthly_fee_cents`, so later price changes on the mailbox do not retroactively alter an existing rental. A new agreement is `PENDING_AUTH`; its `status` ranges over `PENDING_AUTH`, `ACTIVE`, `SUSPENDED`, `CLOSED`, and `ABANDONED`, with `CLOSED` and `ABANDONED` terminal. Its `term_start` and `term_end` are null until activation, its `renewal_count` starts at zero, and its `version` at 1.

**Activation.** A `FacilityOperator` activates a `PENDING_AUTH` agreement. Activation is gated by three cross-entity conditions evaluated together: the referenced `Form1583` must be `VERIFIED` and the referenced `Customer` must be `ACTIVE` — either failing yields `ERR_AUTH_NOT_VERIFIED` — and the referenced `MailboxUnit` must be `VACANT`, failing which yields `ERR_MAILBOX_OCCUPIED`. A mailbox may back exactly one non-terminal rental at a time; activating over a mailbox that is already `RENTED` or is `OUT_OF_SERVICE` — its occupied closed-open interval from `term_start` up to but not including `term_end` still live — is the occupancy conflict that `ERR_MAILBOX_OCCUPIED` reports. On success the agreement moves `PENDING_AUTH → ACTIVE`; the mailbox is driven `VACANT → RENTED`; `term_start` is set to the facility's current clock and `term_end` to `term_start` plus `term_months` times 30 days; and the system opens the agreement's single invoice and posts the first rental charge. That charge is a `CHARGE` ledger entry with reason `RENTAL` whose amount is `monthly_fee_cents` multiplied by `term_months`. If the agreement has autopay enabled, the autopay cascade described in §3.6 runs immediately, capturing a payment that drives the invoice balance to zero.

**Renewal.** While an agreement is `ACTIVE`, the customer (or an operator) may renew it; this is one of the two version-guarded writes. The request carries `expected_rental_agreement_version`, which must equal the agreement's current `version` or the renewal is rejected with `ERR_STALE_VERSION` as described in §2.5. A successful renewal is an `ACTIVE → ACTIVE` self-loop: it increments the agreement's `version` by one, increments `renewal_count` by one, extends `term_end` by another `term_months` times 30 days, and posts a fresh `RENTAL` charge of `monthly_fee_cents` times `term_months` to the open invoice — again triggering the autopay cascade when enabled.

**Suspension and reactivation.** An operator may suspend an `ACTIVE` agreement, and the clock sweep suspends one automatically when its invoice balance climbs past the suspension threshold of 5,000 cents. Either way the agreement moves `ACTIVE → SUSPENDED`, and as a depth-two cascade every forwarding request in `REQUESTED` status whose mail item belongs to this agreement is placed `REQUESTED → ON_HOLD`. Reactivation moves `SUSPENDED → ACTIVE`, but only when the invoice balance has been brought back to at or below that same 5,000-cent threshold; a reactivation attempted while the balance still exceeds the threshold is rejected with `ERR_AGREEMENT_NOT_ACTIVE`. Reactivation reverses the hold cascade, returning every `ON_HOLD` forwarding request on the agreement's mail to `REQUESTED`.

**Closure.** The customer or an operator may close an agreement that is `ACTIVE` or `SUSPENDED`. Closure is blocked while any package on the agreement is still `RECEIVED` or `NOTIFIED` — those are unresolved packages and the attempt is rejected with `ERR_UNRESOLVED_PACKAGES`. On a clean close the agreement moves to `CLOSED`; the mailbox is released `RENTED → VACANT`; a `PRORATED_REFUND` credit is posted per the proration math in §3.7; every `STORED` mail item on the agreement is shredded (`STORED → SHREDDED`) and every `REQUESTED` or `ON_HOLD` forwarding request on those items is cancelled (to `CANCELLED`); and the invoice is settled if its balance is at or below zero, otherwise it stays open.

**Abandonment.** Abandonment is never requested directly; it is produced only by the clock sweep. During a clock advance, an agreement in `PENDING_AUTH`, `ACTIVE`, or `SUSPENDED` whose `term_end` is non-null and whose facility clock has reached or passed `term_end` plus the abandonment grace of 30 days, and whose invoice balance is still above zero, is driven to `ABANDONED`. Abandonment releases the mailbox `RENTED → VACANT`, cascades every package on the agreement still in `RECEIVED` or `NOTIFIED` to `ABANDONED` (each releasing its locker as in §3.4), shreds every `STORED` mail item, and writes off the debt: it posts a `WRITE_OFF` credit equal to the remaining invoice balance and moves the invoice to `WRITTEN_OFF`.

### 3.4. Package Receipt, Notification, and Resolution

When a parcel arrives, a `FacilityOperator` receives it against an `ACTIVE` rental. The receive request carries a `facility_id`, the `rental_agreement_id` it is received for, the `carrier` (`USPS`, `UPS`, `FEDEX`, `AMAZON`, or `OTHER`), the requested `size_tier` (`SMALL`, `MEDIUM`, `LARGE`, or `XL`), and the parcel's `longest_dim_cm` and `weight_g`, each at least 1. Receipt against an agreement that is not `ACTIVE` is rejected with `ERR_AUTH_NOT_VERIFIED`. The system then finds a free locker: it must assign an `AVAILABLE` `LockerUnit` of the requested `size_tier` belonging to the same facility (matched on `facility_id`), and when more than one such locker qualifies it assigns the earliest-created one (ordered by `created_at` ascending, then by insertion order); if none exists the receipt is rejected with `ERR_NO_LOCKER_AVAILABLE`. A locker is occupied by exactly one package at a time — an `OCCUPIED` or `OUT_OF_SERVICE` locker cannot take a second parcel. On success a new `Package` is created in `RECEIVED`, its `locker_unit_id` set to the assigned locker, which is driven `AVAILABLE → OCCUPIED` with its `current_package_id` set to the new package and the facility's `available_locker_count` decremented by one. A six-digit `pickup_code` is minted and held on the package, and the oversize surcharge is computed once and pinned into `oversize_fee_cents` (see §3.5). The package's `notified_at` and `resolved_at` are null until the corresponding milestones, and its `overstay_fee_cents` starts at zero.

A package's `status` runs from `RECEIVED` through `NOTIFIED` and forks into one of four terminal outcomes — `PICKED_UP`, `FORWARDED`, `RETURNED`, or `ABANDONED` — and every one of those four releases the locker. An operator notifies the recipient that a parcel is ready, moving `RECEIVED → NOTIFIED`: this stamps `notified_at` with the facility's current clock, increments the package's `version` by one, and recomputes the provisional overstay fee (which is zero at the moment of notification, since no calendar days have yet elapsed).

**Pickup.** Picking up a `NOTIFIED` package is the second version-guarded write. The request supplies the claimant's `pickup_code` and `expected_package_version`. The package must be `NOTIFIED`; the supplied `expected_package_version` must equal the package's current `version` (else `ERR_STALE_VERSION`, per §2.5); the supplied `pickup_code` must equal the package's stored `pickup_code` (else `ERR_PICKUP_CODE_MISMATCH`); and the owning agreement must be `ACTIVE` or `SUSPENDED` (else `ERR_INVALID_STATE`). On success the package's `version` is incremented again, the overstay fee is finalized against `resolved_at`, `resolved_at` is stamped with the facility clock, and the package moves `NOTIFIED → PICKED_UP`. As a depth-three cascade, the finalized overstay charge (if greater than zero) and the pinned oversize charge (if greater than zero) are posted to the agreement's invoice as `CHARGE` ledger entries with reasons `OVERSTAY` and `OVERSIZE`, raising the balance, after which the autopay cascade captures payment if autopay is enabled. Finally the locker is released: it returns `OCCUPIED → AVAILABLE`, its `current_package_id` is cleared to null, the package's `locker_unit_id` is cleared, and the facility's `available_locker_count` is incremented.

**Forwarding.** The customer or an operator may forward a `NOTIFIED` package to a `destination_address`, but only while the owning agreement is `ACTIVE`; forwarding against a non-active agreement is rejected with `ERR_AGREEMENT_NOT_ACTIVE`. Forwarding moves `NOTIFIED → FORWARDED`: it finalizes the overstay fee against `resolved_at`, stamps `resolved_at`, posts the `OVERSTAY` and `OVERSIZE` charges as on pickup, and additionally posts a `FORWARDING` charge of 1,200 cents for forwarding the parcel itself; autopay then captures if enabled, and the locker is released.

**Return to sender.** An operator may return a package that is `RECEIVED` or `NOTIFIED` to its carrier. This moves the package to `RETURNED`, stamps `resolved_at`, and releases the locker — but posts no overstay or oversize charge at all, since the carrier reclaims the parcel.

**Abandonment.** A package abandons only through the clock sweep or as a cascade from an abandoning agreement. During a clock advance, a package still `RECEIVED` or `NOTIFIED` whose `notified_at` is now at least the package-abandonment window of 14 days in the past is driven to `ABANDONED`. Like pickup and forward, abandonment finalizes the overstay fee, posts the `OVERSTAY` and `OVERSIZE` charges, stamps `resolved_at`, and releases the locker.

### 3.5. Oversize and Overstay Fees

Two distinct surcharges attach to a package, computed at different moments and against different inputs.

The **oversize fee** is pinned once, at receipt, into `oversize_fee_cents`, and never changes thereafter. It penalizes a parcel that exceeds the dimensional or weight envelope of the locker tier it was assigned to. Each tier has a maximum longest-dimension and a maximum weight: the dimension caps are 30 cm for `SMALL`, 50 cm for `MEDIUM`, 80 cm for `LARGE`, and 120 cm for `XL`; the weight caps are 2,000 g for `SMALL`, 5,000 g for `MEDIUM`, 15,000 g for `LARGE`, and 40,000 g for `XL`. To price the overage, the system measures how far the parcel's `longest_dim_cm` exceeds its tier's dimension cap and divides that excess by a 10 cm bucket, rounding up to a whole number of buckets, with no negative buckets when the parcel is within the cap. It does the same for weight, dividing the amount by which `weight_g` exceeds the tier's weight cap by a 1,000 g bucket and rounding up, again floored at zero buckets. Each dimension bucket costs 150 cents and each weight bucket costs 80 cents; the raw fee is the dimension-bucket count times 150 plus the weight-bucket count times 80. That raw fee is then capped: the final `oversize_fee_cents` is the smaller of the raw fee and the cap of 2,000 cents, with the cap applied last after the buckets are summed.

The **overstay fee** accrues by calendar day for a parcel that lingers past a grace period, and it exists in two readings of the same formula. Both work from the same anchor: the calendar date of `notified_at`, interpreted in the facility's `time_zone`. The number of whole calendar days stored is the calendar date of the reference moment minus that anchor date, never negative. From that, the chargeable overstay days are the stored days minus the grace of 2 days, floored at zero — which means a fee begins to accrue only once the parcel has been stored for at least 3 calendar days (the grace of 2 plus 1). The daily rate depends on the assigned locker's `size_tier`: 200 cents per day for `SMALL`, 300 for `MEDIUM`, 500 for `LARGE`, and 800 for `XL`. The overstay fee is the chargeable overstay days multiplied by that daily rate.

The two readings differ only in which reference moment they use. The **provisional** overstay is computed at notification and again on every clock advance, using the facility's live `current_utc` as the reference; it is written to `overstay_fee_cents` so a reader can see the running exposure, but it is not posted to the ledger and may grow as the clock advances. The **final** overstay is computed at the terminal transition — pickup, forward, or abandonment — using the package's `resolved_at` as the reference; this frozen figure is the amount actually posted as the `OVERSTAY` charge to the invoice.

### 3.6. Invoicing, the Ledger, Autopay, and Payments

Each rental has exactly one invoice, opened automatically at activation and never created by a client directly. An `Invoice` references its `rental_agreement_id` and carries a `status` of `OPEN`, `SETTLED`, or `WRITTEN_OFF`, opening in `OPEN`. Its money fields are all derived from the ledger and the payments against it. `charges_total_cents` is the sum of every `LedgerEntry` on the invoice whose `kind` is `CHARGE`; `credits_total_cents` is the sum of those whose `kind` is `CREDIT`; `payments_total_cents` is the sum of `amount_cents` over every `Payment` on the invoice whose `status` is `CAPTURED`. The `balance_cents` is `charges_total_cents` minus `credits_total_cents` minus `payments_total_cents`, and it may go negative, representing an overpayment credit. Because every ledger and payment amount is already an integer-cent line item, the invoice sums those integers directly and never re-rounds a running subtotal.

A `LedgerEntry` is append-only and never mutated. It belongs to an `invoice_id`, carries a `kind` of `CHARGE` or `CREDIT` and a `reason` of `RENTAL`, `OVERSIZE`, `OVERSTAY`, `FORWARDING`, `PRORATED_REFUND`, or `WRITE_OFF`, an `amount_cents` recorded as a positive magnitude with the sign carried by `kind`, and a `source_ref` identifying the originating package, forwarding request, or agreement. Ledger entries are raised by the workflows that cause them — rental charges at activation and renewal, oversize and overstay charges at package resolution, forwarding charges at forwarding completion and at package forward, the prorated-refund credit at closure, and the write-off credit at abandonment.

**Autopay.** When an agreement has `autopay_enabled` true, it runs an autopay capture after any charge posts to its invoice — at activation, renewal, package pickup, package forward, and forwarding-request completion. The rule is precise: immediately after the charge posts and the balance is recomputed, if autopay is on and the invoice's `balance_cents` is greater than zero, the system creates a `Payment` for exactly that positive balance, with `method` `CARD_AUTOPAY` and `status` `CAPTURED`, after which the recomputed balance returns to zero. This is the tail of the depth-three cascade that begins with a package resolution charge.

**Manual payments.** A `Payment` may also be captured by hand against an `invoice_id`, supplying an `amount_cents` of at least 1 and a `method` of `CARD_AUTOPAY`, `CARD_MANUAL`, or `CASH`. Payments are final in this version: a captured payment is `CAPTURED` and stays there. A manual payment whose `amount_cents` exceeds the invoice's positive outstanding `balance_cents` is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`; the same error is returned when the invoice has no positive balance to pay against — that is, when its current `balance_cents` is already at or below zero, any manual payment is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`. After any capture the invoice balance is recomputed, and the invoice moves to `SETTLED` once its balance is at or below zero.

### 3.7. Mail, Forwarding, Scanning, and Proration

Letter mail arriving in a rented box is recorded as a `MailItem` against the `rental_agreement_id` whose mailbox received it, tagged with a `mail_class` of `FIRST_CLASS`, `MARKETING`, `CERTIFIED`, or `PARCEL`. A new mail item is `STORED`; its `status` ranges over `STORED`, `SCANNED`, `FORWARDED`, and `SHREDDED`. It is shredded as a cascade when its agreement closes or abandons, as described in §3.3.

A customer (or operator) raises a `ForwardingRequest` against a stored `mail_item_id`, choosing a `kind` of `FORWARD` or `SCAN`. A `FORWARD` request must supply a `destination_address`, which is required for forwarding and ignored for a scan; omitting it on a forward is the `ERR_INVALID_REQUEST` case noted in §2.10. The service fee is pinned into `fee_cents` at creation: a forward costs 600 cents and a scan costs 150 cents. A new request is `REQUESTED`; its `status` ranges over `REQUESTED`, `ON_HOLD`, `COMPLETED`, and `CANCELLED`, with the last two terminal. As covered in §3.3, suspending the parent agreement parks a `REQUESTED` request at `ON_HOLD` and reactivation returns it to `REQUESTED`; closing the agreement cancels it.

An operator completes a `REQUESTED` forwarding request, but only while the request's mail item's agreement is `ACTIVE`; completion against a non-active agreement is rejected with `ERR_AGREEMENT_NOT_ACTIVE`. Completion moves the request `REQUESTED → COMPLETED`, drives the underlying mail item to `FORWARDED` when the kind is `FORWARD` or to `SCANNED` when the kind is `SCAN`, and posts a `FORWARDING` charge of the pinned `fee_cents` to the agreement's invoice, with autopay capturing afterward if enabled. The customer or system may instead cancel a request that is `REQUESTED` or `ON_HOLD`, moving it to `CANCELLED`.

**Proration on closure.** When an agreement closes, the system refunds the unused portion of the latest term's rental charge, and it does so by the chronological reading of "unused." The term spans `term_months` times 30 days. The refundable amount is the current term's rental charge — `monthly_fee_cents` times `term_months`. The used days are the whole calendar days between `term_start` and the close moment, computed in the facility's `time_zone` and clamped to the closed interval from zero up to the full term length. The chronological refund, which is the variant actually posted as the `PRORATED_REFUND` credit, is the rental charge multiplied by the unused fraction — that is, the rental charge times (term days minus used days), divided by term days, with the division performed before a single round-half-up to whole cents at the very end.

A what-if quote is also available without changing any state, returning both readings of the refund as `chronological_refund_cents` and `forward_looking_refund_cents`; the quote uses the facility's current clock (`current_utc`) as the close-moment reference. An optional `basis` hint may accompany the quote; it is advisory only and never alters the response, which always returns both figures. When the target agreement has not yet been activated — its `term_start` is still null — both figures are returned as zero. The chronological figure is computed exactly as above. The **forward-looking** figure refunds only whole unused months: it is `monthly_fee_cents` multiplied by the months remaining, where the months remaining is `term_months` minus the used days rounded up to a whole number of months (the used days divided by 30, rounded up), and never less than zero. Partial months are not refundable under the forward-looking reading, so the two figures generally diverge; only the chronological figure is ever posted.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`; operations that modify an existing resource — including state transitions and capability invocations — return `200 OK`. Request and response bodies are not restated here; reconstruct them from the workflow narratives in Section 3, which is where field names, fee triggers, and side effects live.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/facilities` | Create a facility | FacilityOperator |
| GET | `/facilities/{id}` | Get a facility with computed locker counts | FacilityOperator, ComplianceOfficer, Customer |
| POST | `/facilities/{id}/clock/advance` | Advance the logical clock; run overstay/abandonment/suspension sweeps | FacilityOperator |
| POST | `/locker-units` | Create a locker | FacilityOperator |
| GET | `/locker-units/{id}` | Get a locker | FacilityOperator, ComplianceOfficer, Customer |
| GET | `/locker-units` | List/filter lockers | FacilityOperator, ComplianceOfficer, Customer |
| POST | `/locker-units/{id}/out-of-service` | Take an available locker out of service | FacilityOperator |
| POST | `/locker-units/{id}/restore` | Restore an out-of-service locker | FacilityOperator |
| POST | `/mailbox-units` | Create a mailbox/PO box | FacilityOperator |
| GET | `/mailbox-units/{id}` | Get a mailbox | FacilityOperator, ComplianceOfficer, Customer |
| GET | `/mailbox-units` | List/filter mailboxes | FacilityOperator, ComplianceOfficer, Customer |
| POST | `/mailbox-units/{id}/out-of-service` | Take a vacant mailbox out of service | FacilityOperator |
| POST | `/mailbox-units/{id}/restore` | Restore an out-of-service mailbox | FacilityOperator |
| POST | `/customers` | Register a customer | FacilityOperator, Customer |
| GET | `/customers/{id}` | Get a customer | FacilityOperator, ComplianceOfficer, Customer |
| GET | `/customers` | List/filter customers | FacilityOperator, ComplianceOfficer |
| POST | `/customers/{id}/suspend` | Suspend a customer | FacilityOperator, ComplianceOfficer |
| POST | `/forms-1583` | Create a draft Form 1583 | FacilityOperator, Customer |
| GET | `/forms-1583/{id}` | Get a Form 1583 | FacilityOperator, ComplianceOfficer, Customer |
| GET | `/forms-1583` | List/filter Form 1583 records | FacilityOperator, ComplianceOfficer, Customer |
| POST | `/forms-1583/{id}/recipients` | Add an authorized recipient to a Form 1583 | FacilityOperator, Customer |
| GET | `/forms-1583/{id}/recipients` | List authorized recipients on a Form 1583 | FacilityOperator, ComplianceOfficer, Customer |
| POST | `/forms-1583/{id}/submit` | Submit or resubmit a Form 1583 | Customer, FacilityOperator |
| POST | `/forms-1583/{id}/verify` | Verify a submitted Form 1583 | ComplianceOfficer |
| POST | `/forms-1583/{id}/reject` | Reject a submitted Form 1583 | ComplianceOfficer |
| POST | `/rental-agreements` | Create a pending rental agreement | FacilityOperator, Customer |
| GET | `/rental-agreements/{id}` | Get a rental agreement | FacilityOperator, ComplianceOfficer, Customer |
| GET | `/rental-agreements` | List/filter rental agreements | FacilityOperator, ComplianceOfficer, Customer |
| GET | `/rental-agreements/{id}/refund-quote` | What-if prorated-refund quote (both variants) | FacilityOperator, Customer |
| POST | `/rental-agreements/{id}/activate` | Activate an agreement | FacilityOperator |
| POST | `/rental-agreements/{id}/renew` | Renew an active agreement (OCC-guarded) | Customer, FacilityOperator |
| POST | `/rental-agreements/{id}/suspend` | Suspend an active agreement | FacilityOperator |
| POST | `/rental-agreements/{id}/reactivate` | Reactivate a suspended agreement | FacilityOperator |
| POST | `/rental-agreements/{id}/close` | Close an agreement | Customer, FacilityOperator |
| POST | `/packages` | Receive a package against an active rental | FacilityOperator |
| GET | `/packages/{id}` | Get a package | FacilityOperator, ComplianceOfficer, Customer |
| GET | `/packages` | List/filter packages | FacilityOperator, ComplianceOfficer, Customer |
| POST | `/packages/{id}/notify` | Notify the recipient a package is ready | FacilityOperator |
| POST | `/packages/{id}/pickup` | Pick up a package with the hold code (OCC-guarded) | FacilityOperator |
| POST | `/packages/{id}/forward` | Forward a package to an address | Customer, FacilityOperator |
| POST | `/packages/{id}/return-to-sender` | Return a package to the carrier | FacilityOperator |
| POST | `/mail-items` | Record letter mail received in a rental's mailbox | FacilityOperator |
| GET | `/mail-items/{id}` | Get a mail item | FacilityOperator, ComplianceOfficer, Customer |
| GET | `/mail-items` | List/filter mail items | FacilityOperator, ComplianceOfficer, Customer |
| POST | `/forwarding-requests` | Request forwarding or scanning of a stored mail item | Customer, FacilityOperator |
| GET | `/forwarding-requests/{id}` | Get a forwarding request | FacilityOperator, ComplianceOfficer, Customer |
| GET | `/forwarding-requests` | List/filter forwarding requests | FacilityOperator, ComplianceOfficer, Customer |
| POST | `/forwarding-requests/{id}/complete` | Complete a forwarding/scan request | FacilityOperator |
| POST | `/forwarding-requests/{id}/cancel` | Cancel a forwarding/scan request | Customer, FacilityOperator |
| GET | `/invoices/{id}` | Get an invoice with computed totals/balance | FacilityOperator, ComplianceOfficer, Customer |
| GET | `/invoices` | List/filter invoices | FacilityOperator, ComplianceOfficer, Customer |
| GET | `/invoices/{id}/ledger-entries` | List ledger entries on an invoice | FacilityOperator, ComplianceOfficer, Customer |
| POST | `/payments` | Capture a manual payment against an invoice | FacilityOperator, Customer |
| GET | `/payments/{id}` | Get a payment | FacilityOperator, ComplianceOfficer, Customer |
| GET | `/payments` | List/filter payments | FacilityOperator, ComplianceOfficer, Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_AUTH_NOT_VERIFIED` | 409 |
| `ERR_PICKUP_CODE_MISMATCH` | 409 |
| `ERR_MAILBOX_OCCUPIED` | 409 |
| `ERR_NO_LOCKER_AVAILABLE` | 409 |
| `ERR_UNRESOLVED_PACKAGES` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_DUPLICATE` | 409 |
| `ERR_NO_RECIPIENTS` | 409 |
| `ERR_INVALID_CLOCK` | 422 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 409 |
| `ERR_MAILBOX_NOT_VACANT` | 409 |
