# Vehicle-Donation Charity API — Product Requirements Document

## 1. Introduction

Every year, thousands of households give away a car they no longer want, expecting two things in return: that the vehicle disappears from their driveway without hassle, and that the paperwork supporting their charitable deduction arrives correctly and on time. Between those two moments sits a surprisingly heavy operational pipeline. A donation offer must be screened, a tow booked against a vendor with finite crews, a paper title cleared through a state DMV that may reject it more than once, the car sold at auction or scrapped for salvage, the sale proceeds split between the program's operating costs and the beneficiary charity, an IRS Form 1098-C valued under whichever of three rules actually applies, and — eventually — real money wired to the charity in a batch that a finance officer other than the one who prepared it has authorised.

This document specifies the backend service that runs that pipeline. The service is a REST API mounted under `/api`. It is deliberately built around two ideas. The first is that a donation carries **two independent lifecycles**: where the vehicle physically is, and where the money is. A car can be sold while its payout is withheld; a donation can be closed for tax purposes while the charity has not yet been paid. Neither axis derives from the other, and the API exposes both. The second idea is that **money movements are journalled, never merely computed**. Every credit and debit against a donation lands in an append-only proceeds ledger, so that a charity's pledged balance is always explainable line by line, and so that reversing a sale is a bookkeeping act rather than an erasure.

The audience for this specification is the engineering team implementing the service. Where a rule involves a threshold, a rounding decision, or an ordering between checks, the rule is stated exactly; readers should treat any figure in this document as normative rather than illustrative.

## 2. Global Specifications & System-Wide Principles

### 2.1. Users and Role-Based Access Control

Authentication is header-based. Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity in which the caller acts. If either header is absent, or if `X-User-Role` is not one of the seven role names defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not among the roles authorised for the requested operation (see the endpoint table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The seven roles are `Donor`, `CharityAdmin`, `IntakeAgent`, `TitleClerk`, `AuctionManager`, `FinanceOfficer`, and `ProgramAdmin`.

Two of these roles are **entity-backed**, meaning the caller's `X-User-ID` is not an arbitrary operator string but the primary key of a stored record:

- When `X-User-Role` is `Donor`, `X-User-ID` is the `id` of the acting donor record; ownership checks on any resource that references a donor compare that resource's `donor_id` to `X-User-ID`.
- When `X-User-Role` is `CharityAdmin`, `X-User-ID` is the `id` of the acting charity affiliate; ownership checks compare a batch's `charity_id`, or a donation's `charity_id`, to `X-User-ID`.

The remaining five roles — `IntakeAgent`, `TitleClerk`, `AuctionManager`, `FinanceOfficer`, and `ProgramAdmin` — carry **opaque** identity. For these roles `X-User-ID` is an operator identifier that is not tied to any persisted entity and is never compared against any record's `id`. The server does record it where the domain demands an audit trail: the officer who issues a receipt is stamped into `issued_by_user_id`, and the officers who close and pay a remittance batch are stamped into `closed_by_user_id` and `paid_by_user_id` respectively.

Ownership violations by an entity-backed role are reported as `ERR_FORBIDDEN_OWNER` (HTTP 403). This check guards exactly four operations: a donor cancelling a donation (the donation's `donor_id` must equal `X-User-ID`), a donor or charity administrator listing donations under a `donor_id` or `charity_id` filter, a charity administrator disputing a closed remittance batch (the batch's `charity_id` must equal `X-User-ID`), and a charity administrator reading the charity-summary report (the `charity_id` requested must equal `X-User-ID`).

`ProgramAdmin` is the program's operating authority: it owns reference data (charities, donors, tow vendors, venues), donor blocks, payout withholding, IRS exception recording, receipt voids, manual follow-up completion, the operations sweep, and the logical clock. `FinanceOfficer` owns the receipt and remittance desk. `IntakeAgent` runs the front office: donation acceptance and decline, drop-off receipt, and the entire tow-scheduling surface. `TitleClerk` owns the title record lifecycle end to end. `AuctionManager` operates the sale floor. `Donor` and `CharityAdmin` are read-mostly external parties with one write capability each — cancellation and dispute respectively.

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

Every list endpoint accepts two optional query parameters. `limit` controls page size: it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. `offset` controls the starting position in the result set: it defaults to 0 and may be no smaller than 0. A `limit` outside the range from 1 to 100 inclusive, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending — oldest record first. The ledger listings and the follow-up-task listing also follow this oldest-first ordering.

For list responses the `meta` object carries four pagination fields: `limit` (the effective page size applied), `offset` (the effective starting position), `total_count` (the number of records matching the filter before pagination is applied), and `has_more` (true when records remain beyond the current page).

### 2.4. Resource Identity, Timestamps and Versioning

Every stored record is addressed by `id`, a server-minted UUID string. Identifiers carry no type prefix — a donation id and a vehicle id are indistinguishable by shape, and clients must never parse them. Clients never supply `id` on creation.

Records also carry `created_at`, the instant the record was written, formatted as an ISO 8601 UTC timestamp with three fractional-second digits. Most records additionally carry `updated_at`, refreshed on every mutation of that record and initially equal to `created_at`, and `version`, an integer that begins at 1 when the record is created and increases by exactly 1 on every mutation of that record.

One entity is deliberately leaner. Proceeds ledger entries are immutable journal lines: they carry `id` and `created_at` only. They have no `updated_at` and no `version`, because a ledger line is never edited — a mistake is corrected by appending a compensating line, never by amending the original.

### 2.5. The Logical Clock

The service does not read wall-clock time for domain decisions. It maintains a **logical clock** whose value is exactly `2026-07-01T00:00:00Z` until an administrator moves it, and which never falls back to real time. An administrator moves the clock by supplying a `to_iso8601` instant to the clock-setting capability, which answers with the resulting `current_utc` value.

Every domain instant the server writes is drawn from the logical clock: `created_at` and `updated_at` on all records, the tow completion instant `actual_pickup_utc`, the DMV filing instant `submitted_at_utc`, the lot listing instant `listed_at_utc`, the sale instant `sold_at_utc`, the receipt issue instant `issued_at_utc`, and the follow-up deadline `due_utc`. Every comparison against "now" — window validity, task escalation, batch period membership, venue daily capacity — is likewise made against the logical clock.

### 2.6. Money, Precision and Rounding

All monetary quantities in this system are integers denominated in **whole cents**; there are no fractional-cent balances anywhere. Wherever a monetary formula produces a non-integral intermediate, the result is rounded **half up** to whole cents — a value exactly at the half-cent boundary rounds away from zero, upward.

Two rounding disciplines matter enough to state globally. First, when a chain of multiplicative factors is applied, the factors are multiplied at full precision and the product is rounded **once**, at the point the specification names — never factor by factor. Second, when a total is assembled from many lines, whether the rounding happens per line or once on the sum is a material choice that changes the answer by up to one cent per line; the remittance-fee rules in §3.9 depend on precisely this distinction and specify each variant separately.

Percentage inputs (`remittance_fee_pct`, `commission_pct`) are stored as fractions, not as percentage points: a ten percent fee is stored as the number 0.10.

### 2.7. Optimistic Concurrency

Three write operations require the caller to prove it is acting on a current view of a parent record, by echoing that record's `version` back to the server. The version field is a required part of the request body in each case, not an optional hint; omitting it is `ERR_INVALID_REQUEST`.

**Reserving a tow window.** Creating a pickup order requires `expected_donation_version`, carrying the client's last observed `version` of the donation being towed. If it does not equal the donation's current `version`, the create is rejected with `ERR_STALE_DONATION_VERSION` (HTTP 412). A fresh pickup order legitimately supersedes an earlier failed one under the retry policy, so a writer whose view of the donation predates that failure — or predates a pickup reset, or a cancellation — would otherwise book a tow window against a stale attempt count.

**Recording a sale.** Recording the hammer price on an auction lot likewise requires `expected_donation_version` matching the donation's current `version`, and a mismatch is rejected with `ERR_STALE_DONATION_VERSION` (HTTP 412). A relist legitimately supersedes the prior lot, so a stale donation view means the money fields the caller believes it is overwriting are no longer the current ones.

**Paying a remittance batch.** Paying a closed batch requires `expected_batch_version` matching the batch's current `version`; a mismatch is rejected with `ERR_STALE_BATCH_VERSION` (HTTP 412). A dispute-and-reopen cycle legitimately supersedes the frozen member set, so a stale batch view means the caller is authorising a payout against figures that no longer hold.

No other operation takes a version field. Where an operation is not named above, callers must not send one and the server must not require one.

### 2.8. The Order in Which Requests Are Judged

Many operations in this program are guarded by several checks at once, and which rejection the caller sees is itself part of the contract. Checks are evaluated in the fixed order below, and the **first** check that fails determines the response; later checks are not evaluated at all.

1. **Authentication.** Both headers present and `X-User-Role` among the seven declared roles — otherwise `ERR_UNAUTHENTICATED`.
2. **Role authorisation.** The acting role appears among the roles listed for the endpoint in §4 — otherwise `ERR_UNAUTHORIZED`.
3. **Path resolution.** Every identifier embedded in the URL path resolves to a stored row, validated left to right. Applies to every path-parameterised endpoint. The rejection names the entity that failed to resolve: `ERR_DONOR_NOT_FOUND`, `ERR_CHARITY_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_TITLE_RECORD_NOT_FOUND`, `ERR_TOW_VENDOR_NOT_FOUND`, `ERR_PICKUP_ORDER_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_AUCTION_LOT_NOT_FOUND`, `ERR_TAX_RECEIPT_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, or `ERR_TASK_NOT_FOUND`, each HTTP 404.
4. **Ownership.** For the entity-backed roles, `X-User-ID` matches the resource's owning foreign key — otherwise `ERR_FORBIDDEN_OWNER`. This applies to donation cancellation, donation listing under a `donor_id` or `charity_id` filter, batch dispute, and the charity-summary report.
5. **Request shape.** Every required body field is present and of the declared type, enum members are legal values, integers required to be positive are positive, and pagination parameters are in range — otherwise `ERR_INVALID_REQUEST`.
6. **Body foreign keys.** Every foreign key supplied in the request body resolves to a stored row, reported with that entity's not-found code. This applies to donation creation, vehicle creation, title-record creation, pickup-order creation, auction-lot creation, tax-receipt creation, and remittance-batch creation.
7. **Segregation of duties.** The officer paying a batch is not the officer recorded in `closed_by_user_id` — otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This applies to batch payment only.
8. **Optimistic concurrency.** The supplied expected version equals the parent's current `version`. Pickup-order creation and sale recording use `ERR_STALE_DONATION_VERSION`; batch payment uses `ERR_STALE_BATCH_VERSION`. Both are HTTP 412.
9. **Source-state legality.** The target resource sits in a state from which the requested transition is declared. The rejection names the entity whose state blocked the call: `ERR_INVALID_DONATION_STATE`, `ERR_INVALID_TITLE_STATE`, `ERR_INVALID_PICKUP_STATE`, `ERR_INVALID_LOT_STATE`, `ERR_INVALID_RECEIPT_STATE`, `ERR_INVALID_BATCH_STATE`, or `ERR_INVALID_TASK_STATE`, each HTTP 409. This applies to every transition endpoint.
10. **Payout-axis legality.** The donation's `payout_status` permits the requested money movement — otherwise `ERR_INVALID_PAYOUT_STATE` (HTTP 409). This guards voiding a sale, withholding a payout, and paying a batch.
11. **Donor standing.** The referenced donor is `ACTIVE` — otherwise `ERR_DONOR_BLOCKED` (HTTP 409). This guards donation creation and donation acceptance.
12. **Charity standing.** The referenced charity affiliate is `ACTIVE` — otherwise `ERR_CHARITY_SUSPENDED` (HTTP 409). This guards donation creation, donation acceptance, remittance-batch creation, and batch close.
13. **Counterparty standing.** The tow vendor is `ACTIVE` and the sales venue is `ACTIVE`. Pickup-order creation and pickup completion report `ERR_VENDOR_SUSPENDED`; auction-lot creation, sale recording, and relisting report `ERR_VENUE_SUSPENDED`. Both are HTTP 409.
14. **Title clearance.** A title record exists for the donation and its `state` is `CLEARED` — otherwise `ERR_TITLE_NOT_CLEARED` (HTTP 409). This guards sale recording, receipt drafting, and receipt issue.
15. **Resubmission budget.** A rejected title may be refiled only while it has been rejected no more than twice — otherwise `ERR_TITLE_RESUBMIT_LIMIT` (HTTP 409). This guards title resubmission.
16. **Receipt uniqueness.** The donation has no tax receipt in `DRAFT` or `ISSUED` — otherwise `ERR_RECEIPT_ALREADY_ACTIVE` (HTTP 409). This guards receipt drafting.
17. **Asset record present.** A vehicle row exists for the donation, because the receipt's fallback valuation reads its fair-market estimate — otherwise `ERR_VEHICLE_RECORD_MISSING` (HTTP 409). This guards receipt drafting.
18. **One-per-parent and natural-key uniqueness on assets.** Vehicle creation rejects a second vehicle for the same donation with `ERR_DUPLICATE_VEHICLE` and, only after that check passes, a repeated `vin` with `ERR_DUPLICATE_VIN`; title-record creation rejects a second title record for the same donation with `ERR_DUPLICATE_TITLE_RECORD`. All three are HTTP 409.
19. **Settlement immutability.** The donation is not frozen into a batch whose `status` is `CLOSED` or `PAID` — otherwise `ERR_DONATION_SETTLED` (HTTP 409). This guards voiding a sale and withholding a payout.
20. **Interval sanity.** The end of an interval is strictly after its start. Pickup-order creation reports `ERR_PICKUP_WINDOW_INVALID`; remittance-batch creation reports `ERR_BATCH_PERIOD_INVALID`. Both are HTTP 422.
21. **No backdated tows.** `scheduled_start_utc` is at or after the current logical clock — otherwise `ERR_PICKUP_IN_PAST` (HTTP 422). This guards pickup-order creation.
22. **Vendor window separation.** The requested window does not collide with another scheduled window on the same vendor — otherwise `ERR_VENDOR_WINDOW_CONFLICT` (HTTP 409). This guards pickup-order creation; the collision rule is spelled out in §3.5.
23. **Vendor capacity.** The vendor's scheduled-order count after the create would not exceed its `daily_capacity_slots` — otherwise `ERR_VENDOR_CAPACITY_EXCEEDED` (HTTP 409). This guards pickup-order creation.
24. **Attempt budget.** The donation's `pickup_attempts` is strictly less than three — otherwise `ERR_PICKUP_ATTEMPTS_EXCEEDED` (HTTP 409). This guards pickup-order creation.
25. **Venue daily capacity.** The venue hosts fewer than five same-day lots — otherwise `ERR_VENUE_CAPACITY_EXCEEDED` (HTTP 409). This guards auction-lot creation and relisting; the counting rule is spelled out in §3.6.
26. **Registry uniqueness.** Donor registration rejects a repeated `email` with `ERR_DUPLICATE_EMAIL`; charity registration rejects a repeated `ein` with `ERR_DUPLICATE_EIN`. Both are HTTP 409.
27. **Reserve met.** The hammer price is at least the lot's `reserve_price_cents` — otherwise `ERR_RESERVE_NOT_MET` (HTTP 422). This guards sale recording.
28. **Non-empty batch.** The batch's eligible member set is non-empty at close time — otherwise `ERR_BATCH_EMPTY` (HTTP 422). This guards batch close.
29. **Fee range.** The charity's `remittance_fee_pct` is at least 0 and at most 0.30 — otherwise `ERR_FEE_PCT_OUT_OF_RANGE` (HTTP 422). This guards charity registration.

The practical consequence worth internalising: a suspended venue surfaces before a missing title, a missing title surfaces before an unmet reserve, and a stale version surfaces before any state check at all.

### 2.9. Cascades, Version Bumps and Consistency

A great many operations in this program touch more than one record. Whenever an operation is described as mutating a record, that record's `updated_at` is refreshed and its `version` increases by one — including when the mutation is a *consequence* of an operation aimed at a different record. Recording a tow completion, for example, is aimed at a pickup order but also advances the donation, and the donation's `version` moves as a result. This is precisely why the concurrency rules of §2.7 exist: the donation's version is a busy number.

Derived counters are maintained incrementally but must always equal the value a full recount would produce. `TowVendor.booked_slots_count` is the number of that vendor's pickup orders whose `status` is `SCHEDULED`: it rises by one whenever an order is created and falls by one whenever an order leaves `SCHEDULED` by completion, failure, or cancellation. `Donor.donation_count` is the number of that donor's donations whose `status` is not `CANCELLED`. `Donation.pickup_attempts` is the number of that donation's pickup orders that reached `FAILED`. Balances on a charity affiliate — `pledged_balance_cents` and `remitted_balance_cents` — follow the ledger rules of §2.10.

### 2.10. The Proceeds Ledger Principle

Money never moves silently. Every credit or debit the program books against a donation is appended to the **proceeds ledger** as an immutable entry recording which donation it belongs to (`donation_id`), which batch it belongs to if any (`remittance_batch_id`), what kind of movement it is (`entry_type`), which way it points (`direction`), how large it is (`amount_cents`), and a human-readable `memo` explaining its provenance.

`entry_type` is one of `PROCEEDS_CREDIT`, `PROGRAM_FEE_DEBIT`, `TOW_COST_DEBIT`, `ADMIN_FEE_DEBIT`, `REVERSAL`, `REMITTANCE_SETTLEMENT`, or `CHARITY_FEE_DEBIT`. `direction` is either `CREDIT` or `DEBIT`. `amount_cents` is always an unsigned magnitude of at least zero; the sign lives in `direction`, such that an entry's signed contribution is its `amount_cents` when the direction is `CREDIT` and the negative of its `amount_cents` when the direction is `DEBIT`.

Most entries belong to a single donation. Batch-level entries — specifically the `CHARITY_FEE_DEBIT` written when a batch closes — carry no donation and leave `donation_id` empty. An entry's `remittance_batch_id` stays empty until the entry is bound to a batch.

### 2.11. Follow-Up Obligations

The program tracks its own loose ends as follow-up tasks. A task always names the donation it concerns (`donation_id`), why it was raised (`task_type`, one of `RECEIPT_DELIVERY`, `PICKUP_ESCALATION`, `TITLE_STALE`, or `REMITTANCE_PENDING`), the deadline after which it becomes overdue (`due_utc`), and the `assigned_role` expected to resolve it. A task's `status` starts at `OPEN`, may move to `ESCALATED` when it ages past its deadline, and ends at `DONE`. Whenever a task is completed — by hand or by the system act that made it moot — a `resolution_note` is recorded explaining why it closed. Tasks are never created by clients directly; they appear as consequences of other operations.

### 2.12. Reading Nested Collections

Several read endpoints are nested beneath a parent — a donation's ledger entries, a donation's follow-up tasks, a batch's ledger entries. For these, the parent identifier in the path is resolved first, and a parent that does not exist yields that parent's not-found code rather than an empty list. Only once the parent resolves are the collection's own filters and pagination applied.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Program's Counterparties

Before a single car can be donated, four kinds of counterparty must exist in the system, and all four are registered by a `ProgramAdmin` (donor registration being the one exception, which an `IntakeAgent` may also perform).

A **charity affiliate** is registered with its legal `name`, its IRS employer identification number `ein`, and the two-letter uppercase `state_code` in which it is registered. Both `name` and `ein` are required, and `ein` must be unique across all affiliates — a repeat registration is refused with `ERR_DUPLICATE_EIN`. The affiliate may optionally declare `remittance_fee_pct`, the fraction of a remittance batch's gross that the program retains at payout time; when omitted it defaults to 0.10, and any supplied value must be at least 0 and at most 0.30, a ceiling the program's board has fixed. A new affiliate begins with `status` of `ACTIVE` and with both `pledged_balance_cents` and `remitted_balance_cents` initialised to 0. An affiliate that misbehaves can be moved to `SUSPENDED`; a suspended affiliate may accept no new donations and no new batches, and any attempt reports `ERR_CHARITY_SUSPENDED`. Charity records are readable individually — including their live balances — by every role except the donor, and the full affiliate listing, optionally filtered by `status`, is available to program administrators and finance officers.

A **donor** is registered with `email`, `full_name` (the legal name that will be printed on the tax receipt) and a two-letter uppercase `state_code` of residence. Email addresses are unique across donors; a collision reports `ERR_DUPLICATE_EMAIL`. A newly registered donor is `ACTIVE` with a `donation_count` of 0. An administrator may move a donor to `BLOCKED` by supplying a `reason`; a blocked donor may not have new donations recorded, and neither existing offers from that donor may be accepted — both paths report `ERR_DONOR_BLOCKED`. A donor record may be read by the front office, administrators, finance, and by that donor.

A **tow vendor** is registered with `name`, the two-letter uppercase `service_state_code` it serves, its `hourly_rate_cents` (which must be greater than zero), and `daily_capacity_slots`, the maximum number of simultaneously reserved tow jobs it will accept, also greater than zero. Vendors begin `ACTIVE` with `booked_slots_count` at 0, and may be moved to `SUSPENDED`, after which no new reservation and no completion may be booked against them — reported as `ERR_VENDOR_SUSPENDED`.

A **sales venue** is registered with `name`, a `venue_type` of `AUCTION`, `SALVAGE`, or `DIRECT_SALE`, and its two-letter uppercase `state_code`. Venues may declare `commission_pct`, defaulting to 0.05; this figure is reported for the operator's benefit but is deliberately **not** deducted anywhere in the proceeds waterfall. Venues begin `ACTIVE` and may be moved to `SUSPENDED`, blocking new listings, sales, and relists with `ERR_VENUE_SUSPENDED`. Suspending a charity, a vendor, or a venue advances that record's own `version`.

### 3.2. Taking In a Donation

A donation offer is recorded by an intake agent or a program administrator against a payload naming the `donor_id` and the beneficiary `charity_id`, the `intake_channel` through which the offer arrived (`WEB`, `PHONE`, or `PARTNER`), and the `declared_condition` the donor self-reports — one of `EXCELLENT`, `GOOD`, `FAIR`, `POOR`, or `SALVAGE`. The payload may also set `pickup_required`, which defaults to true and means the program must tow the vehicle; setting it false signals that the donor will drive the car in themselves. Recording the offer raises the donor's `donation_count` by one. The new donation opens on both axes at once: its disposition `status` is `PENDING_REVIEW` and its money-side `payout_status` is `PENDING`.

Screening comes next. An intake agent **accepts** an offer that is still `PENDING_REVIEW`, moving it `PENDING_REVIEW → ACCEPTED`; acceptance is refused if the donor is not `ACTIVE` or the beneficiary affiliate is not `ACTIVE`. An agent may instead **decline** the offer with a `reason`, moving it `PENDING_REVIEW → DECLINED` and simultaneously driving the money axis `PENDING → WITHHELD`. Declining moves no money, because at that point `net_to_charity_cents` is still zero and there is nothing to reverse. Both acceptance and decline are refused with `ERR_INVALID_DONATION_STATE` from any other disposition.

Donors may withdraw. A **cancellation** — available to the donation's own donor, and also to a program administrator — carries a `reason` and is permitted while the donation is in either `PENDING_REVIEW` or `ACCEPTED`; it drives the donation to `CANCELLED`. Cancellation lowers the donor's `donation_count` by one and releases logistics: every pickup order for that donation still sitting in `SCHEDULED` is cancelled, and each such cancellation lowers that vendor's `booked_slots_count` by one. When the caller is a donor, `X-User-ID` must equal the donation's `donor_id`.

An administrator may record an IRS exception against a donation by supplying `exception_type`, which is one of `NONE`, `MATERIAL_IMPROVEMENT`, `GIFT_TO_NEEDY`, or `SIGNIFICANT_USE` and which defaults to `NONE` on every new donation. The exception is a claim that the program materially improved the vehicle, gave it to a needy individual, or made significant intervening use of it, and — as §3.8 explains — it changes which valuation rule the donor's receipt uses.

Donations are readable individually by every role, and listable with any combination of `donor_id`, `charity_id`, `status`, and `payout_status` filters. A donation read exposes both state axes and every money field: `fmv_estimate_cents` (which mirrors the vehicle's fair-market estimate and is empty while no vehicle record exists), `gross_proceeds_cents`, `program_fee_cents`, `tow_allowance_cents`, `net_to_charity_cents` — all four of which start at 0 — and `deduction_amount_cents`, which is empty until a receipt is issued. The disposition axis ranges over `PENDING_REVIEW`, `ACCEPTED`, `PICKUP_BLOCKED`, `IN_CUSTODY`, `SOLD`, `UNSOLD`, `CLOSED`, `DECLINED`, and `CANCELLED`, of which `CLOSED`, `DECLINED`, and `CANCELLED` are terminal. The money axis ranges over `PENDING`, `ACCRUED`, `REMITTED`, and `WITHHELD`, of which `REMITTED` and `WITHHELD` are terminal.

### 3.3. The Asset Record and What the Car Is Worth

Once an offer exists, the physical asset is described. An intake agent or an auction manager attaches exactly one asset record to a donation, naming the `donation_id` it describes together with the vehicle's `vin`, its `year`, its `make`, its `model`, and a `base_book_value_cents` figure taken from a third-party guide. The model `year` must be at least 1900 and at most 2100; `base_book_value_cents` must be strictly greater than zero; the `vin` must be unique across all asset records, and a donation may carry at most one. A second attempt against the same donation is refused with `ERR_DUPLICATE_VEHICLE`, and a `vin` already on file is refused with `ERR_DUPLICATE_VIN` — in that order, so a caller re-posting the same vehicle to the same donation sees the duplicate-vehicle answer. The payload may also set `salvage_flag`, defaulting to false, indicating the car is titled or graded as scrap, and `keys_present`, defaulting to true, recording whether keys came with the car.

At creation the record carries `inspected` as false, with `odometer_miles` and `condition_grade` both empty until somebody looks at the car. The first inspection — an update by an auction manager or intake agent — may supply any of `odometer_miles`, `condition_grade` (one of `EXCELLENT`, `GOOD`, `FAIR`, `POOR`, `SALVAGE`), `salvage_flag`, and `keys_present`, and always sets `inspected` to true.

Both creation and inspection produce a fair-market estimate, written to `fmv_estimate_cents` and mirrored onto the donation's own `fmv_estimate_cents`, with the donation's `version` advancing as a result. Which of two valuation variants ran is recorded in `fmv_variant`.

The estimate is built as follows. Start from `base_book_value_cents` and apply two multipliers to it. The **condition multiplier** is one for an `EXCELLENT` grade, eighty-five hundredths for `GOOD`, sixty-five hundredths for `FAIR`, forty hundredths for `POOR`, and fifteen hundredths for `SALVAGE`. The **odometer multiplier** is one when the mileage is unknown, and otherwise one for a reading of seventy-five thousand miles or fewer, eighty-five hundredths for a reading above seventy-five thousand but no more than one hundred and fifty thousand, and seventy hundredths for anything higher. Multiply the base book value by both multipliers at full precision and round that single product half up to whole cents. If the asset carries `salvage_flag` as true, the rounded figure is then capped at seventy-five thousand cents — that is, the lesser of the rounded figure and seventy-five thousand is taken. Finally, whether or not the cap applied, the result is floored at ten thousand cents: an estimate below that floor is raised to it. The order is fixed — one rounding after the full product, then the salvage cap, then the floor.

The two variants differ only in which grade and mileage feed the formula. At creation, the vehicle has not been inspected, and the `BASE_CONDITION` variant runs: the grade is taken from the donation's `declared_condition` and the mileage is treated as unknown, so the odometer multiplier is forced to one regardless of any reading supplied later. On every inspection update the `POST_INSPECTION` variant runs instead: the grade is the record's own `condition_grade` and the mileage is its `odometer_miles`, so a high-mileage car can settle below the figure the donor's self-report produced for the identical `base_book_value_cents`. Asset records are readable individually and listable, optionally filtered by `donation_id`, by the front office, sale floor, finance, administrators, and the title desk.

### 3.4. Clearing Title at the DMV

Nothing may be sold that the program does not legally own, so the title desk runs its own lifecycle in parallel with everything else. A `TitleClerk` opens exactly one title record per donation, naming the `donation_id` together with the state-issued `title_number` and the `owner_name` printed on the paper title; the optional `lien_holder` records a lienholder of record and is left empty when the title is free and clear. A second title record for the same donation is refused with `ERR_DUPLICATE_TITLE_RECORD`. A new record opens in `state` of `DRAFT` with `rejection_count` at 0, and with `rejection_reason`, `dmv_filing_reference`, and `submitted_at_utc` all empty.

Filing with the DMV moves the record `DRAFT → SUBMITTED`, and is permitted only while the associated donation sits in one of `ACCEPTED`, `PICKUP_BLOCKED`, `IN_CUSTODY`, or `UNSOLD`. On filing, the server mints a `dmv_filing_reference` string and stamps `submitted_at_utc` from the logical clock.

The DMV answers by way of a decision recorded against the submitted record, carrying an `outcome` of either `CLEARED` or `REJECTED`. A cleared outcome moves the record `SUBMITTED → CLEARED`, which is terminal and is the gate every sale and every receipt is measured against. A rejected outcome moves it `SUBMITTED → REJECTED`, raises `rejection_count` by one, and stores the supplied `rejection_reason`. A decision recorded against a record that is not `SUBMITTED` is refused with `ERR_INVALID_TITLE_STATE`.

A rejected title can be refiled. Resubmission moves the record `REJECTED → SUBMITTED`, re-mints `dmv_filing_reference`, restamps `submitted_at_utc`, and may optionally correct the `title_number` or the `owner_name` in the same call. The program tolerates two DMV rejections: a resubmission is accepted while `rejection_count` is no greater than two, so the first and second rejections may both be refiled, but a third rejection leaves the count at three and the next resubmission is refused with `ERR_TITLE_RESUBMIT_LIMIT`.

When refiling is hopeless, the clerk abandons the title with a `reason`, moving it `REJECTED → ABANDONED` — the other terminal state. Abandoning raises a follow-up obligation of type `TITLE_STALE`, opened for that donation, assigned to `TitleClerk`, and due fifteen days after the current logical clock. Title records are readable individually and listable with optional `donation_id` and `state` filters.

### 3.5. Getting the Car Into Custody

Most donated cars have to be collected. An intake agent reserves a tow window by naming the `donation_id`, the `tow_vendor_id` who will do the work, the inclusive window start `scheduled_start_utc` and the exclusive window end `scheduled_end_utc`, together with the `expected_donation_version` described in §2.7. The window must be coherent — the end strictly after the start, otherwise `ERR_PICKUP_WINDOW_INVALID` — and it may not be backdated: a start strictly before the current logical clock is refused with `ERR_PICKUP_IN_PAST`, while a start exactly at the current clock is accepted.

Vendors need turnaround time between jobs, so reserved windows on the same vendor must stand ninety minutes apart. Concretely, a proposed window collides with an existing scheduled window on that vendor when the proposed start falls strictly before the existing end extended by ninety minutes **and** the existing start falls strictly before the proposed end extended by ninety minutes; a collision is refused with `ERR_VENDOR_WINDOW_CONFLICT`. Windows are half-open, covering their start instant but not their end instant, and a new window beginning exactly ninety minutes after an existing window's end is therefore accepted. Beyond separation, the vendor's overall load is capped: if adding this reservation would push the vendor's count of `SCHEDULED` orders above its `daily_capacity_slots`, the request is refused with `ERR_VENDOR_CAPACITY_EXCEEDED`. And the program will not chase a car forever — a donation whose `pickup_attempts` has already reached three admits no further reservation, refused with `ERR_PICKUP_ATTEMPTS_EXCEEDED`.

A reservation that survives all of that is created in `status` of `SCHEDULED`, raises the vendor's `booked_slots_count` by one, and records `attempt_number` as one more than the donation's `pickup_attempts` at that moment. Its `actual_pickup_utc` and `failure_reason` start empty and `actual_tow_cost_cents` starts at 0.

From `SCHEDULED` a reservation forks three ways, each with its own consequences.

**Completion.** An agent records a successful tow together with the billed `actual_tow_cost_cents`. This is permitted only while the order is `SCHEDULED`, the donation is `ACCEPTED`, and the vendor is `ACTIVE`. The order moves `SCHEDULED → COMPLETED`, `actual_pickup_utc` is stamped from the logical clock, the billed cost is stored, the vendor's `booked_slots_count` falls by one, and the donation moves `ACCEPTED → IN_CUSTODY`.

**Failure.** An agent records a failed attempt with a `failure_reason`, permitted while the order is `SCHEDULED` and the donation is `ACCEPTED`. The order moves `SCHEDULED → FAILED`, the reason is stored, the vendor's `booked_slots_count` falls by one, and the donation's `pickup_attempts` rises by one. When that increment brings the count to three or beyond, the donation moves `ACCEPTED → PICKUP_BLOCKED`, and that blockage in turn opens a follow-up obligation of type `PICKUP_ESCALATION`, `OPEN`, assigned to `ProgramAdmin`, and due fifteen days after the current logical clock.

**Cancellation.** An agent releases a reserved window with a `reason`, permitted while the order is `SCHEDULED`. The order moves `SCHEDULED → CANCELLED` and the vendor's `booked_slots_count` falls by one — but, unlike a failure, the donation's `pickup_attempts` is left untouched. A release is not an attempt.

Any of these three against an order that is not `SCHEDULED` is refused with `ERR_INVALID_PICKUP_STATE`.

A blocked donation is not dead. A program administrator resets the pickup with a `reason`, moving the donation `PICKUP_BLOCKED → ACCEPTED`, resetting `pickup_attempts` to 0, and marking every `PICKUP_ESCALATION` follow-up on that donation that is still `OPEN` or `ESCALATED` as `DONE` with a `resolution_note` of exactly `pickup reset`. The cycle `ACCEPTED → PICKUP_BLOCKED → ACCEPTED` may repeat as often as the operation requires.

Where the donor drives the car in instead, no tow exists at all. An agent records the drop-off against an `ACCEPTED` donation whose `pickup_required` is false, moving it directly `ACCEPTED → IN_CUSTODY`. A drop-off recorded against a donation that expects a tow, or that is not `ACCEPTED`, is refused with `ERR_INVALID_DONATION_STATE`. Pickup orders are readable individually and listable with optional `donation_id`, `tow_vendor_id`, and `status` filters, by the front office, administrators, and finance.

### 3.6. The Sale Floor

A donation in custody is offered for sale. An auction manager lists it by naming the `donation_id`, the `venue_id` hosting the sale, the venue-assigned `lot_number`, and the `reserve_price_cents` — the minimum acceptable hammer price, which must be at least zero. Listing is refused when the venue is not `ACTIVE`. Venues also have a physical constraint on how many cars they can put through the block in a day: a venue may host at most five lots whose listing instant falls on the same UTC calendar day — the day running from midnight inclusive to the next midnight exclusive — as the current logical clock, counting only lots whose `status` is not `WITHDRAWN`. A sixth is refused with `ERR_VENUE_CAPACITY_EXCEEDED`.

A new lot opens in `status` of `LISTED` with `listed_at_utc` stamped from the logical clock, `relist_count` at 0, and `sale_price_cents`, `sold_at_utc`, and `void_reason` all empty. The lot lifecycle spans `LISTED`, `SOLD`, `NO_SALE`, `VOIDED`, and `WITHDRAWN`; only `WITHDRAWN` is terminal, and the others cycle.

**Recording a sale.** The manager supplies the hammer price as `sale_price_cents` together with `expected_donation_version`. The sale is permitted only when the lot is `LISTED`, the venue is `ACTIVE`, a title record exists for the donation with `state` of `CLEARED` (otherwise `ERR_TITLE_NOT_CLEARED`), the donation is `IN_CUSTODY`, the echoed version matches, and the hammer price is at least the lot's `reserve_price_cents` (otherwise `ERR_RESERVE_NOT_MET`). The lot moves `LISTED → SOLD` with `sale_price_cents` and `sold_at_utc` recorded, the donation moves `IN_CUSTODY → SOLD`, and the proceeds waterfall of §3.7 runs.

**Recording a no-sale.** When the block passes on a lot, the manager records the outcome with an optional `reason`. The lot moves `LISTED → NO_SALE` and the donation moves `IN_CUSTODY → UNSOLD`. Nothing financial happens: the donation's `payout_status` stays `PENDING` and `relist_count` is unchanged.

**Relisting.** A lot in either `NO_SALE` or `VOIDED` may be returned to the block, supplying a fresh `reserve_price_cents`. Relisting requires the venue to be `ACTIVE` and is subject to the same five-lots-per-venue-per-day ceiling as an initial listing. The lot moves back to `LISTED`, `listed_at_utc` is restamped from the logical clock, `relist_count` rises by one, and the donation moves `UNSOLD → IN_CUSTODY`. The cycle `IN_CUSTODY → UNSOLD → IN_CUSTODY` may repeat.

**Voiding a sale.** A recorded sale can be undone with a `void_reason`, permitted while the lot is `SOLD`, the donation's `payout_status` is `ACCRUED`, and the donation has not been frozen into a batch that is `CLOSED` or `PAID` — that last condition being refused with `ERR_DONATION_SETTLED`, because settled money cannot be unwound. The lot moves `SOLD → VOIDED` with `void_reason` stored and both `sale_price_cents` and `sold_at_utc` cleared, the donation moves `SOLD → UNSOLD`, and the entire proceeds cascade is reversed as §3.7 describes.

**Withdrawing.** A lot in either `LISTED` or `NO_SALE` may be pulled from the sale entirely with a `reason`, moving it to `WITHDRAWN` and freeing its slot in the venue's daily count for that calendar day. When the withdrawn lot was `LISTED`, the donation moves `IN_CUSTODY → UNSOLD` as well; a lot withdrawn from `NO_SALE` leaves the donation where it already is, in `UNSOLD`.

Any of these acts against a lot in a state that does not admit it is refused with `ERR_INVALID_LOT_STATE`; where the donation's own disposition is the obstacle, the refusal is `ERR_INVALID_DONATION_STATE`. Lots are readable individually and listable with optional `donation_id`, `venue_id`, and `status` filters.

### 3.7. Splitting the Proceeds

The moment a hammer falls, the program has to decide how much of the money belongs to the charity. This is a waterfall: each step consumes the output of the one before it, and no step is ever re-evaluated once a later step has run. The order matters because the tow allowance is capped as a fraction of a figure that itself already has the program fee taken out of it.

Begin with the gross — the lot's `sale_price_cents`. From the gross, determine the program's tiered rate: fifteen percent when the gross is one thousand dollars (one hundred thousand cents) or less; twelve percent when the gross exceeds that but is five thousand dollars (five hundred thousand cents) or less; ten percent above that.

*Step one — the program fee.* Multiply the gross by that rate and round the product half up to whole cents. The program never retains less than fifty dollars (five thousand cents), so if the rounded figure falls below that floor, the floor is used instead. It also never retains more than the sale itself brought in, so the result is finally capped at the gross. The outcome is written to `program_fee_cents`.

*Step two — the provisional balance.* Subtract the program fee from the gross. This provisional figure is not persisted; it exists to feed the next two steps.

*Step three — the tow allowance.* Look up the tow cost actually billed: the `actual_tow_cost_cents` of the pickup order for this donation whose `status` is `COMPLETED`. There can be at most one such order, because the donation leaves `ACCEPTED` on the first completion; orders sitting in `SCHEDULED`, `FAILED`, or `CANCELLED` contribute nothing, and when no completed order exists at all the billed cost is treated as zero. The program reimburses the tow, but only up to a quarter of the provisional balance: take twenty-five hundredths of the provisional balance, round that half up to whole cents, and use the **lesser** of the billed cost and that ceiling. The outcome is written to `tow_allowance_cents`.

*Step four — the charity's net.* From the provisional balance subtract the tow allowance and subtract a flat administrative fee of twenty-five dollars (two thousand five hundred cents). If the arithmetic goes negative, the net is zero rather than a debt. The outcome is written to `net_to_charity_cents`, and the gross itself is written to `gross_proceeds_cents`. Rounding happens exactly twice in this waterfall — once at step one and once at step three; no other step rounds.

The sale then drives a four-link cascade. **First**, the donation's money axis moves `PENDING → ACCRUED`, which happens when the computed net is greater than zero. **Second**, the accrual journals itself: a `PROCEEDS_CREDIT` entry is appended as a `CREDIT` for the gross, a `PROGRAM_FEE_DEBIT` as a `DEBIT` for the program fee, a `TOW_COST_DEBIT` as a `DEBIT` for the tow allowance — omitted entirely when the allowance is zero — and an `ADMIN_FEE_DEBIT` as a `DEBIT` for the two-thousand-five-hundred-cent administrative fee; and the beneficiary affiliate's `pledged_balance_cents` rises by the donation's net. **Third**, that balance increase can trip an automatic sweep: when the affiliate's `pledged_balance_cents` reaches or exceeds five thousand dollars (five hundred thousand cents) and that affiliate has no remittance batch currently in `OPEN`, `CLOSED`, or `DISPUTED`, the system opens a batch for it with `status` of `OPEN`, `period_start_utc` at the current logical clock and `period_end_utc` thirty days later. **Fourth**, an auto-opened batch raises a follow-up obligation of type `REMITTANCE_PENDING`, `OPEN`, assigned to `FinanceOfficer` and due fifteen days after the current logical clock, recorded against the donation whose sale triggered the sweep.

Voiding the sale unwinds all of it symmetrically. The donation's four money fields — `gross_proceeds_cents`, `program_fee_cents`, `tow_allowance_cents`, and `net_to_charity_cents` — return to 0, the money axis moves `ACCRUED → PENDING`, a single `REVERSAL` entry is appended as a `DEBIT` whose `amount_cents` equals the donation's net **as it stood immediately before the void**, and the affiliate's `pledged_balance_cents` falls by that same pre-void net. A void is refused when any batch that is `CLOSED` or `PAID` already holds a `REMITTANCE_SETTLEMENT` entry for that donation.

Administrators have one further money lever. **Withholding a payout**, supplied with a `reason`, drives the money axis to `WITHHELD` and is permitted while `payout_status` is either `PENDING` or `ACCRUED`; from any other value it is refused with `ERR_INVALID_PAYOUT_STATE`. Withholding from `PENDING` moves nothing, since nothing has accrued. Withholding from `ACCRUED` is a genuine reversal: it requires that the donation not already be frozen into a `CLOSED` or `PAID` batch (otherwise `ERR_DONATION_SETTLED`), lowers the affiliate's `pledged_balance_cents` by the donation's `net_to_charity_cents`, and appends one `REVERSAL` entry as a `DEBIT` for that same amount. `WITHHELD` is terminal on the money axis.

A donation's journal is readable oldest-first by finance, administrators, the sale floor, and the beneficiary charity, optionally filtered by `entry_type`.

### 3.8. What the Donor May Claim

The donor's tax paperwork is the program's other deliverable, and it is a finance officer's responsibility. A receipt is drafted against a `donation_id` and is only possible for a donation whose disposition is `SOLD` or `UNSOLD`; donations in `PENDING_REVIEW`, `ACCEPTED`, `PICKUP_BLOCKED`, `IN_CUSTODY`, `CLOSED`, `DECLINED`, or `CANCELLED` are not eligible for a receipt at all. Drafting further requires that the donation already have an asset record, since the fallback valuation reads its fair-market estimate — otherwise `ERR_VEHICLE_RECORD_MISSING` — and that its title be `CLEARED`. A donation may hold at most one receipt that is not voided; a second attempt while one sits in `DRAFT` or `ISSUED` is refused with `ERR_RECEIPT_ALREADY_ACTIVE`.

Drafting runs the valuation and opens the receipt in `status` of `DRAFT`, with `control_number`, `issued_at_utc`, `issued_by_user_id`, and `void_reason` empty and `reissue_count` at 0. It also opens a follow-up obligation of type `RECEIPT_DELIVERY`, `OPEN`, assigned to `FinanceOfficer`, due thirty days after the current logical clock.

The valuation itself picks exactly one of three rules, tested in this order against the donation:

- If the donation carries any `exception_type` other than `NONE`, the `FMV_FULL` rule applies: `valuation_variant` is `FMV_FULL`, `form_type` is `FORM_1098C_BOX_4B`, and `claimed_amount_cents` is the donation's full `fmv_estimate_cents`. This is the branch that lets a materially improved car, a car given to a needy individual, or a car the charity itself used be claimed at appraised value rather than at what it fetched.
- Otherwise, if the donation's `gross_proceeds_cents` is **strictly greater than** five hundred dollars (fifty thousand cents), the `GROSS_PROCEEDS` rule applies: `valuation_variant` is `GROSS_PROCEEDS`, `form_type` is `FORM_1098C_BOX_4A`, and `claimed_amount_cents` is the `gross_proceeds_cents` itself, ignoring the fair-market estimate entirely.
- Otherwise the `FMV_SAFE_HARBOR` rule applies: `valuation_variant` is `FMV_SAFE_HARBOR`, `form_type` is `ACKNOWLEDGMENT_ONLY`, and `claimed_amount_cents` is the lesser of the donation's `fmv_estimate_cents` and fifty thousand cents.

The comparison in the second rule is strict: gross proceeds landing exactly on fifty thousand cents take the safe-harbour branch, not the gross-proceeds branch. No rounding occurs in this calculation — both inputs are already whole cents.

**Issuing** the receipt moves it `DRAFT → ISSUED`. It requires the receipt to be in `DRAFT`, the donation to be `SOLD` or `UNSOLD`, and the title to still be `CLEARED`. On issue the server mints a sequential `control_number`, stamps `issued_at_utc` from the logical clock and `issued_by_user_id` from the acting officer's `X-User-ID`, and **recomputes** `claimed_amount_cents`, `form_type`, and `valuation_variant` against the donation as it stands at that moment — a draft written before an exception was recorded is therefore corrected at issue rather than issued stale. Issuing also closes the donation: it moves `SOLD → CLOSED` or `UNSOLD → CLOSED`, copies `claimed_amount_cents` onto the donation's `deduction_amount_cents`, and marks every `RECEIPT_DELIVERY` follow-up on that donation still `OPEN` or `ESCALATED` as `DONE` with a `resolution_note` of exactly `receipt issued`.

**Voiding** an issued receipt is an administrator's act, carrying a `void_reason`. It moves the receipt `ISSUED → VOIDED`, stores the reason, and clears `control_number`. It also reopens the donation from `CLOSED` and clears `deduction_amount_cents`: the donation returns to `SOLD` when its `gross_proceeds_cents` is greater than zero, and to `UNSOLD` when its `gross_proceeds_cents` is zero.

**Reissuing** returns a voided receipt to the desk. It requires the receipt to be `VOIDED` and the donation to be `SOLD` or `UNSOLD`, moves the receipt `VOIDED → DRAFT`, raises `reissue_count` by one, clears `void_reason`, and recomputes `claimed_amount_cents`, `form_type`, and `valuation_variant` against the donation's current fields. The receipt cycle `DRAFT → ISSUED → VOIDED → DRAFT` has no terminal state; a receipt acted on from a state that does not admit the act is refused with `ERR_INVALID_RECEIPT_STATE`. Receipts are readable individually and listable with optional `donation_id` and `status` filters, by finance, administrators, and the donor.

### 3.9. Paying the Charity

Money reaches a charity in batches. A finance officer opens one by naming the `charity_id` and the sale-date window it sweeps: `period_start_utc` inclusive and `period_end_utc` exclusive, the end strictly after the start. Opening is refused when the affiliate is not `ACTIVE`. A batch opens in `status` of `OPEN` with `donation_count`, `gross_cents`, `fee_cents`, and `net_cents` all 0, `closed_by_user_id`, `paid_by_user_id`, `payment_reference`, and `dispute_reason` all empty, and its provisional fee computed immediately.

Membership is decided by a single eligibility filter, evaluated freshly whenever the batch is not yet frozen. A donation is a member when its `charity_id` matches the batch's, its `payout_status` is `ACCRUED`, its `net_to_charity_cents` is greater than zero, the auction lot for that donation whose `status` is `SOLD` has a `sold_at_utc` falling in the half-open window — at or after `period_start_utc` and strictly before `period_end_utc` — and the donation is not already frozen into another batch that is `CLOSED` or `PAID`. Members are considered in order of the donation's `created_at` ascending.

The fee the program retains is computed two ways, and the difference between them is deliberate. The batch's gross is the sum of the members' `net_to_charity_cents`. The rate is the affiliate's `remittance_fee_pct`.

- The **provisional** figure, exposed as `provisional_fee_cents`, uses batch rounding: multiply the summed gross by the rate and round that single product half up to whole cents. It is recomputed on every read of an `OPEN` batch, alongside `gross_cents`, so the officer always sees a live estimate.
- The **final** figure, written into `fee_cents`, uses per-line rounding: multiply each member's `net_to_charity_cents` by the rate, round each of those products half up to whole cents, and sum the rounded lines. Because each line rounds independently, the frozen `fee_cents` can exceed `provisional_fee_cents` for the very same member set — a set of lines each sitting just below a half-cent can round the batch-rounded figure down by as much as one cent per member relative to the per-line figure.

**Closing** the batch freezes it. Closing requires the batch to be `OPEN`, the affiliate to be `ACTIVE`, and the eligible member set to be non-empty — an empty set is refused with `ERR_BATCH_EMPTY`. On close the member set is frozen, `donation_count` is written as the number of frozen members, `gross_cents` as their summed nets, `fee_cents` as the per-line figure, and `net_cents` as the gross less that final fee. The close also journals: one `REMITTANCE_SETTLEMENT` entry is appended per member donation with its `remittance_batch_id` bound to this batch, plus a single batch-level `CHARITY_FEE_DEBIT` entry carrying no donation and an `amount_cents` equal to `fee_cents`. The acting officer's `X-User-ID` is stored in `closed_by_user_id`, and the batch moves `OPEN → CLOSED`.

**Paying** the batch is the segregation-of-duties gate. It requires the batch to be `CLOSED`, the acting officer's `X-User-ID` to differ from the `closed_by_user_id` recorded at close — the officer who prepared a payout may never authorise it, and an attempt is refused with `ERR_SEGREGATION_OF_DUTIES` — and the `expected_batch_version` to match. The call carries a `payment_reference` capturing the external transfer, which is stored alongside `paid_by_user_id`, and the batch moves `CLOSED → PAID`, its terminal state. Payment then cascades: every member donation moves `ACCRUED → REMITTED` on the money axis; for each such donation the affiliate's `pledged_balance_cents` falls by that donation's `net_to_charity_cents` while its `remitted_balance_cents` rises by that donation's net share — its `net_to_charity_cents` less the per-line rounded fee computed for that same donation; and every `REMITTANCE_PENDING` follow-up on each of those donations still `OPEN` or `ESCALATED` is marked `DONE` with a `resolution_note` of exactly `batch paid`.

**Disputing** is the charity's escape hatch. A `CharityAdmin` whose `X-User-ID` equals the batch's `charity_id` may dispute a `CLOSED` batch by supplying a `dispute_reason`, moving it `CLOSED → DISPUTED` and blocking payment.

**Reopening** returns a disputed batch to the officer's desk. Supplied with a `reason`, it moves the batch `DISPUTED → OPEN`, deletes every `REMITTANCE_SETTLEMENT` and `CHARITY_FEE_DEBIT` entry bound to this batch — thereby unfreezing the member set, which will be recomputed live from the eligibility filter again — and resets `donation_count`, `gross_cents`, `fee_cents`, and `net_cents` to 0 and `closed_by_user_id` to empty. The cycle `OPEN → CLOSED → DISPUTED → OPEN` may repeat. Any batch act from a state that does not admit it is refused with `ERR_INVALID_BATCH_STATE`.

Batches are readable individually — a read of an `OPEN` batch refreshing its live gross and provisional fee — and listable with optional `charity_id` and `status` filters. A batch's own ledger entries are readable oldest-first with an optional `entry_type` filter. All three reads are open to finance, administrators, and the beneficiary charity.

### 3.10. Chasing Loose Ends and Reporting

Follow-up obligations arise in four ways, all of them consequences of other work: a drafted receipt raises a `RECEIPT_DELIVERY` task due in thirty days; a donation blocked after three failed tows raises a `PICKUP_ESCALATION` task due in fifteen days; an abandoned title raises a `TITLE_STALE` task due in fifteen days; and an auto-opened remittance batch raises a `REMITTANCE_PENDING` task due in fifteen days. Each records the `assigned_role` expected to act — `FinanceOfficer` for receipt delivery and remittance, `ProgramAdmin` for pickup escalation, `TitleClerk` for stale titles.

Tasks close in two ways. A program administrator may close one **by hand**, supplying a `resolution_note`; this is permitted from either `OPEN` or `ESCALATED` and moves the task to `DONE`, its terminal state. Closing an already-`DONE` task is refused with `ERR_INVALID_TASK_STATE`. Alternatively, the system closes a task the moment the condition that raised it is resolved: issuing the receipt closes `RECEIPT_DELIVERY` tasks, paying the batch closes `REMITTANCE_PENDING` tasks, and resetting the pickup closes `PICKUP_ESCALATION` tasks — in each case the `resolution_note` is the fixed literal named in the workflow above, and in each case both `OPEN` and `ESCALATED` tasks are swept up.

A periodic **operations checkpoint**, run by a program administrator, does two things and reports what it did. First, every task that is still `OPEN` and whose `due_utc` is at or before the current logical clock moves `OPEN → ESCALATED`. Second, every title record still sitting in `SUBMITTED` whose `submitted_at_utc` is more than forty-five days before the current logical clock, and which has no `TITLE_STALE` task already `OPEN` or `ESCALATED`, gets one raised. The checkpoint answers with `escalated_task_count`, the number of tasks it escalated, and `stale_title_task_count`, the number of stale-title tasks it created. Tasks are readable individually by the front office, the title desk, finance, and administrators, and a donation's tasks are listable oldest-first with optional `status` and `task_type` filters.

Finally, the program offers a computed view of a charity's financial position, addressed by `charity_id` and available to finance, administrators, and that charity itself. It reports the affiliate's stored `pledged_balance_cents` and `remitted_balance_cents` directly; `accrued_donation_count`, the number of that charity's donations whose `payout_status` is `ACCRUED`; `unremitted_net_cents`, the sum of `net_to_charity_cents` across those same accrued donations; and `ledger_signed_total`, the signed sum over every ledger entry whose donation belongs to that charity — adding `amount_cents` for a `CREDIT` and subtracting it for a `DEBIT`. The report considers the charity's donations regardless of disposition, and deliberately excludes batch-level entries that carry no donation from `ledger_signed_total`. No rounding is applied; every figure is already in whole cents.


## 4. Endpoint Definitions

All paths below are absolute. Operations that create a new resource answer with HTTP 201; every other successful operation, including state transitions and reads, answers with HTTP 200. Request and response payloads are not repeated here — the fields each operation accepts, and the consequences it triggers, are specified in the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/api/charities` | register a beneficiary charity affiliate | `ProgramAdmin` |
| GET | `/api/charities/{id}` | read one charity affiliate including its live balances | `ProgramAdmin`, `FinanceOfficer`, `CharityAdmin`, `IntakeAgent`, `AuctionManager`, `TitleClerk` |
| GET | `/api/charities` | list charity affiliates | `ProgramAdmin`, `FinanceOfficer` |
| POST | `/api/charities/{id}/suspend` | suspend a charity affiliate so no new donations or batches may be booked to it | `ProgramAdmin` |
| POST | `/api/donors` | register a donor | `IntakeAgent`, `ProgramAdmin` |
| GET | `/api/donors/{id}` | read one donor | `IntakeAgent`, `ProgramAdmin`, `FinanceOfficer`, `Donor` |
| POST | `/api/donors/{id}/block` | block a donor from creating further donations | `ProgramAdmin` |
| POST | `/api/tow-vendors` | register a tow operator | `ProgramAdmin` |
| GET | `/api/tow-vendors/{id}` | read one tow vendor including booked_slots_count | `ProgramAdmin`, `IntakeAgent`, `FinanceOfficer` |
| POST | `/api/tow-vendors/{id}/suspend` | suspend a tow vendor | `ProgramAdmin` |
| POST | `/api/venues` | register an auction or salvage venue | `ProgramAdmin` |
| GET | `/api/venues/{id}` | read one sales venue | `ProgramAdmin`, `AuctionManager`, `FinanceOfficer` |
| POST | `/api/venues/{id}/suspend` | suspend a sales venue | `ProgramAdmin` |
| POST | `/api/_clock/set_current_utc` | test-driving endpoint that moves the server's logical clock. Before any call the logical clock reads exactly 2026-07-01T00:00:00Z and never falls back to real wall-clock time. | `ProgramAdmin` |
| POST | `/api/donations` | record a donation offer | `IntakeAgent`, `ProgramAdmin` |
| GET | `/api/donations/{id}` | read one donation including both state axes and all money fields | `IntakeAgent`, `TitleClerk`, `AuctionManager`, `FinanceOfficer`, `ProgramAdmin`, `CharityAdmin`, `Donor` |
| GET | `/api/donations` | list donations, filtered by donor, charity, disposition status or payout status | `IntakeAgent`, `TitleClerk`, `AuctionManager`, `FinanceOfficer`, `ProgramAdmin`, `CharityAdmin`, `Donor` |
| POST | `/api/donations/{id}/accept` | accept a donation offer into the program | `IntakeAgent` |
| POST | `/api/donations/{id}/decline` | decline a donation offer | `IntakeAgent` |
| POST | `/api/donations/{id}/cancel` | donor withdraws a donation before it is taken into custody | `Donor`, `ProgramAdmin` |
| POST | `/api/donations/{id}/receive-dropoff` | record that a donor delivered the vehicle themselves | `IntakeAgent` |
| POST | `/api/donations/{id}/reset-pickup` | clear a pickup block so tow scheduling can resume | `ProgramAdmin` |
| POST | `/api/donations/{id}/withhold-payout` | withhold the charity payout for a donation | `ProgramAdmin` |
| POST | `/api/donations/{id}/exception` | record an IRS 1098-C exception that switches the receipt to the full-FMV valuation | `ProgramAdmin` |
| GET | `/api/donations/{id}/ledger-entries` | list the proceeds ledger entries recorded against a donation, oldest first | `FinanceOfficer`, `ProgramAdmin`, `AuctionManager`, `CharityAdmin` |
| GET | `/api/donations/{id}/follow-up-tasks` | list the follow-up tasks raised for a donation, oldest first | `IntakeAgent`, `TitleClerk`, `FinanceOfficer`, `ProgramAdmin` |
| POST | `/api/vehicles` | attach the asset record to a donation and compute the BASE_CONDITION FMV estimate | `IntakeAgent`, `AuctionManager` |
| GET | `/api/vehicles/{id}` | read one vehicle record | `IntakeAgent`, `AuctionManager`, `FinanceOfficer`, `ProgramAdmin`, `TitleClerk` |
| GET | `/api/vehicles` | list vehicle records, optionally filtered by donation | `IntakeAgent`, `AuctionManager`, `FinanceOfficer`, `ProgramAdmin`, `TitleClerk` |
| PATCH | `/api/vehicles/{id}` | record an inspection and recompute the FMV estimate under the POST_INSPECTION variant | `AuctionManager`, `IntakeAgent` |
| POST | `/api/title-records` | open a title clearance record for a donation | `TitleClerk` |
| GET | `/api/title-records/{id}` | read one title record | `TitleClerk`, `ProgramAdmin`, `AuctionManager`, `FinanceOfficer` |
| GET | `/api/title-records` | list title records, optionally filtered by donation | `TitleClerk`, `ProgramAdmin`, `AuctionManager`, `FinanceOfficer` |
| POST | `/api/title-records/{id}/submit-dmv` | file the title with the DMV | `TitleClerk` |
| POST | `/api/title-records/{id}/dmv-decision` | record the DMV's answer on a submitted title | `TitleClerk` |
| POST | `/api/title-records/{id}/resubmit` | refile a rejected title with the DMV | `TitleClerk` |
| POST | `/api/title-records/{id}/abandon` | give up on clearing a rejected title | `TitleClerk` |
| POST | `/api/pickup-orders` | reserve a tow window with a vendor for an accepted donation | `IntakeAgent` |
| GET | `/api/pickup-orders/{id}` | read one pickup order | `IntakeAgent`, `ProgramAdmin`, `FinanceOfficer` |
| GET | `/api/pickup-orders` | list pickup orders, optionally filtered by donation or vendor | `IntakeAgent`, `ProgramAdmin`, `FinanceOfficer` |
| POST | `/api/pickup-orders/{id}/complete` | record a successful tow and its billed cost | `IntakeAgent` |
| POST | `/api/pickup-orders/{id}/fail` | record a failed tow attempt | `IntakeAgent` |
| POST | `/api/pickup-orders/{id}/cancel` | release a reserved tow window | `IntakeAgent` |
| POST | `/api/auction-lots` | list a donation in a venue's sale | `AuctionManager` |
| GET | `/api/auction-lots/{id}` | read one auction lot | `AuctionManager`, `ProgramAdmin`, `FinanceOfficer` |
| GET | `/api/auction-lots` | list auction lots, optionally filtered by donation or venue | `AuctionManager`, `ProgramAdmin`, `FinanceOfficer` |
| POST | `/api/auction-lots/{id}/record-sale` | record the hammer price and run the proceeds waterfall | `AuctionManager` |
| POST | `/api/auction-lots/{id}/record-no-sale` | record that a lot failed to sell | `AuctionManager` |
| POST | `/api/auction-lots/{id}/relist` | return an unsold or voided lot to the block | `AuctionManager` |
| POST | `/api/auction-lots/{id}/void-sale` | reverse a recorded sale and unwind the proceeds cascade | `AuctionManager` |
| POST | `/api/auction-lots/{id}/withdraw` | pull a lot out of the sale entirely | `AuctionManager` |
| POST | `/api/tax-receipts` | draft the donor's tax receipt and select its valuation variant | `FinanceOfficer` |
| GET | `/api/tax-receipts/{id}` | read one tax receipt | `FinanceOfficer`, `ProgramAdmin`, `Donor` |
| GET | `/api/tax-receipts` | list tax receipts, optionally filtered by donation | `FinanceOfficer`, `ProgramAdmin`, `Donor` |
| POST | `/api/tax-receipts/{id}/issue` | issue the receipt to the donor and close the donation | `FinanceOfficer` |
| POST | `/api/tax-receipts/{id}/void` | void an issued receipt | `ProgramAdmin` |
| POST | `/api/tax-receipts/{id}/reissue` | return a voided receipt to draft and revalue it | `FinanceOfficer` |
| POST | `/api/remittance-batches` | open a remittance batch sweeping a charity's accrued donations over a sale-date window | `FinanceOfficer` |
| GET | `/api/remittance-batches/{id}` | read one remittance batch; while OPEN the provisional_fee_cents is recomputed on every read | `FinanceOfficer`, `ProgramAdmin`, `CharityAdmin` |
| GET | `/api/remittance-batches` | list remittance batches, optionally filtered by charity | `FinanceOfficer`, `ProgramAdmin`, `CharityAdmin` |
| GET | `/api/remittance-batches/{id}/ledger-entries` | list the settlement and fee ledger entries bound to a batch, oldest first | `FinanceOfficer`, `ProgramAdmin`, `CharityAdmin` |
| POST | `/api/remittance-batches/{id}/close` | freeze the batch member set and compute the final per-line fee | `FinanceOfficer` |
| POST | `/api/remittance-batches/{id}/pay` | pay out a closed batch; the officer who closed it may not pay it | `FinanceOfficer` |
| POST | `/api/remittance-batches/{id}/dispute` | charity disputes a closed batch before payment | `CharityAdmin` |
| POST | `/api/remittance-batches/{id}/reopen` | reopen a disputed batch, unfreezing its member set | `FinanceOfficer` |
| GET | `/api/follow-up-tasks/{id}` | read one follow-up task | `IntakeAgent`, `TitleClerk`, `FinanceOfficer`, `ProgramAdmin` |
| POST | `/api/follow-up-tasks/{id}/complete` | close a follow-up task by hand | `ProgramAdmin` |
| POST | `/api/_ops/run-sweep` | ops-run checkpoint: escalates every OPEN FollowUpTask whose due_utc has passed and raises TITLE_STALE tasks for titles submitted more than STALE_TITLE_DAYS (45) ago | `ProgramAdmin` |
| GET | `/api/reports/charity-summary` | computed read: a charity's pledged and remitted balances plus its unremitted accrual | `FinanceOfficer`, `ProgramAdmin`, `CharityAdmin` |

## 5. Error Code Catalogue

The conditions that raise each of these codes are stated in the narratives of §2 and §3, next to the rule each one guards.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DONOR_NOT_FOUND` | 404 |
| `ERR_CHARITY_NOT_FOUND` | 404 |
| `ERR_DONATION_NOT_FOUND` | 404 |
| `ERR_VEHICLE_NOT_FOUND` | 404 |
| `ERR_TITLE_RECORD_NOT_FOUND` | 404 |
| `ERR_TOW_VENDOR_NOT_FOUND` | 404 |
| `ERR_PICKUP_ORDER_NOT_FOUND` | 404 |
| `ERR_VENUE_NOT_FOUND` | 404 |
| `ERR_AUCTION_LOT_NOT_FOUND` | 404 |
| `ERR_TAX_RECEIPT_NOT_FOUND` | 404 |
| `ERR_BATCH_NOT_FOUND` | 404 |
| `ERR_TASK_NOT_FOUND` | 404 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_STALE_DONATION_VERSION` | 412 |
| `ERR_STALE_BATCH_VERSION` | 412 |
| `ERR_INVALID_DONATION_STATE` | 409 |
| `ERR_INVALID_PAYOUT_STATE` | 409 |
| `ERR_INVALID_TITLE_STATE` | 409 |
| `ERR_INVALID_PICKUP_STATE` | 409 |
| `ERR_INVALID_LOT_STATE` | 409 |
| `ERR_INVALID_RECEIPT_STATE` | 409 |
| `ERR_INVALID_BATCH_STATE` | 409 |
| `ERR_INVALID_TASK_STATE` | 409 |
| `ERR_DONOR_BLOCKED` | 409 |
| `ERR_CHARITY_SUSPENDED` | 409 |
| `ERR_VENDOR_SUSPENDED` | 409 |
| `ERR_VENUE_SUSPENDED` | 409 |
| `ERR_TITLE_NOT_CLEARED` | 409 |
| `ERR_TITLE_RESUBMIT_LIMIT` | 409 |
| `ERR_RECEIPT_ALREADY_ACTIVE` | 409 |
| `ERR_VEHICLE_RECORD_MISSING` | 409 |
| `ERR_DUPLICATE_VEHICLE` | 409 |
| `ERR_DUPLICATE_VIN` | 409 |
| `ERR_DUPLICATE_TITLE_RECORD` | 409 |
| `ERR_DONATION_SETTLED` | 409 |
| `ERR_PICKUP_WINDOW_INVALID` | 422 |
| `ERR_BATCH_PERIOD_INVALID` | 422 |
| `ERR_PICKUP_IN_PAST` | 422 |
| `ERR_VENDOR_WINDOW_CONFLICT` | 409 |
| `ERR_VENDOR_CAPACITY_EXCEEDED` | 409 |
| `ERR_PICKUP_ATTEMPTS_EXCEEDED` | 409 |
| `ERR_VENUE_CAPACITY_EXCEEDED` | 409 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_DUPLICATE_EIN` | 409 |
| `ERR_RESERVE_NOT_MET` | 422 |
| `ERR_BATCH_EMPTY` | 422 |
| `ERR_FEE_PCT_OUT_OF_RANGE` | 422 |
