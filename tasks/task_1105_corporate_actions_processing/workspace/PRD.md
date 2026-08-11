# Corporate Actions Desk API — Product Requirements Document

## 1. Introduction

Corporate actions are among the highest-risk workflows on a brokerage operations desk. A single stock split, merger, spin-off, dividend, or rights offering touches every client holding the security, and the desk learns of each event through competing announcement channels — custodian feeds, vendor feeds, and depository notices — that routinely disagree on terms. Before any client account can be adjusted, the desk must scrub those raw notifications into one authoritative golden record, project who is entitled to what, firm those projections up when the record date arrives, collect voluntary elections from clients under a hard deadline, and only then book the event against tax lots and cash balances. Mistakes do not stay contained: a mis-booked spin-off corrupts cost basis, and a missed entitlement becomes a client compensation claim.

This document specifies the Corporate Actions Desk API, the system of record for that entire lifecycle. It governs event ingestion and scrubbing, entitlement projection and record-date capture, election collection, mandatory and voluntary event booking with fractional-share cash-in-lieu, cost basis adjustment across tax lots, compensation claims with a desk-funded pool, and reconciliation against custodian statements with automatic break detection. All deadline, record-date, and filing-window rules are evaluated against a server-side logical clock so that desk behavior is deterministic and auditable. Precision is contractual throughout: rounding orders, allocation evaluation orders, and window boundary inclusivity are pinned down in the sections that follow, and an implementation is expected to reproduce them exactly.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and boilerplate that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes seven distinct roles: `DeskAdministrator`, `VendorFeed`, `EventAnalyst`, `OperationsManager`, `AccountHolder`, `ClaimsExaminer`, and `CustodianFeed`. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted on the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The meaning of `X-User-ID` depends on the presented role. When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `DeskAdministrator`, `VendorFeed`, `EventAnalyst`, `OperationsManager`, `ClaimsExaminer`, or `CustodianFeed`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `scrubbed_by_user_id` and `confirmed_by_user_id` on a corporate action event, `applied_by_user_id` on an amendment, `booked_by_user_id` on a booking, or `filed_by_user_id` and `reviewed_by_user_id` on a claim — but it does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, and accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Desk's Logical Clock

All temporal rules in this document — record-date capture, election deadlines, booking windows, and claim filing windows — are evaluated against a server-maintained logical clock, never against wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly 2026-05-01T00:00:00Z and the server must never fall back to wall-clock time. A `DeskAdministrator` may advance the clock through the clock-setting endpoint, supplying the target instant as `to_iso8601`; the response carries the new clock value as `current_utc`. Advancing the clock mutates no entity; it only changes the instant against which deadlines and windows are judged.

### 2.5. Common Resource Properties and Immutability Classes

Most resources in the system share a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 timestamp in UTC with three fractional digits (for example, 2026-05-01T09:15:00.123Z), set when the resource is created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- **`version` (integer):** a system-managed integer that increments by one on every mutation of the resource and underpins optimistic concurrency control.

Three resource types are deliberately immutable audit or ledger records and carry **only** `id` and `created_at` — both `updated_at` and `version` are absent from them: a `SourceNotification` (an ingest record), an `EventAmendment` (an audit record of a terms replacement), and a `BookingLine` (a ledger line). These records are never modified after creation; corrections are expressed by superseding or reversing records rather than by editing history.

### 2.6. Money, Quantities, and Rounding Conventions

Cash is represented as integer cents everywhere — in stored fields, in request payloads, and in responses. No fractional cents ever appear. Share quantities are decimal numbers carried to a maximum of four decimal places; derived quantities are likewise computed and stored at four decimal places.

Where a calculation must round, the method is part of the contract. Quantities and percentages that need rounding are rounded half-up to four decimal places unless stated otherwise. Converting a fractional share position into a cash-in-lieu payment is governed per event by the event's `fractional_policy` terms key, which takes one of three values: `ROUND_HALF_UP`, under which an exact half-cent result rounds up; `ROUND_DOWN`, under which any fractional cent is truncated; and `ROUND_UP`, under which any nonzero fractional cent rounds up, so any nonzero fractional share position yields at least one cent. As an illustration of the three policies on identical inputs, half a share cashed at 3333 cents per share produces 1666.5 cents before policy rounding, which becomes 1667 cents under `ROUND_HALF_UP`, 1666 cents under `ROUND_DOWN`, and 1667 cents under `ROUND_UP`.

Rounding order is pinned wherever per-lot and account-aggregate computations coexist: the desk computes per lot first and sums second, and a sum of per-lot floors is not the same as the floor of the sum. The business sections below call out every place this ordering is load-bearing.

### 2.7. Optimistic Concurrency Control

Two write operations on a corporate action event are guarded by optimistic concurrency control, because both must be evaluated against the event terms the caller actually observed. A request to `POST /api/events/{id}/amendments` must carry `expected_event_version`, a non-optional field holding the event `version` the client last read. A request to `POST /api/events/{id}/elections` must likewise carry `expected_event_version`. In both cases, if the supplied value does not equal the event's current `version` — because a prior amendment, a confirmation, an election submission, or any other version-bumping mutation has advanced it since the client last read the event — the request is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412), and no change is applied. Endpoints not named in this subsection do not accept a version field at all.

### 2.8. Segregation of Duties

Two decisions on this desk are too sensitive to be made by one person, and the system enforces four-eyes control mechanically. The analyst who confirms an event must be a different individual from the analyst who scrubbed it: confirmation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the caller's `X-User-ID` equals the event's `scrubbed_by_user_id`. Symmetrically, the examiner who decides a claim must not be the person who filed it: a claim decision is rejected with `ERR_SEGREGATION_OF_DUTIES` when the caller's `X-User-ID` equals the claim's `filed_by_user_id`.

### 2.9. Derived Balances and Immediate Consistency

Every account carries three derived figures that the server recomputes eagerly on each contributing mutation, so that any read — including the response of the very request that caused the change — reflects the new state immediately. An account's `cash_balance_cents` is its `opening_cash_cents` plus the sum of every cash delta ever applied to it: booking line credits and debits, rights-exercise debits, claim payments, and the inverse lines posted by a booking reversal. The balance is allowed to go negative; when it does, the desk settles the shortfall externally. An account's `total_cost_basis_cents` is the sum of `cost_basis_total_cents` over its `OPEN` position lots only; a lot that has been fully surrendered stops contributing. An account's `pending_entitlement_count` is the count of its entitlements currently in `PROJECTED` or `FIRM` status. Each recomputation is a mutation of the account record and therefore refreshes the account's `updated_at` and increments its `version`.

### 2.10. Validation Order and Resource Existence

Every request is validated in a fixed order, and a failure at any step prevents evaluation of the steps that follow. The order is: first, the presence and non-emptiness of the two identity headers; second, whether the presented role is permitted on the endpoint; third, request shape — required fields present, types valid, enumeration members valid, and, for event creation, terms coherence; fourth, existence of every referenced resource; fifth, account-holder ownership where the endpoint acts on a client account; sixth, state preconditions of the target entity; seventh, the optimistic-concurrency version match where the endpoint participates; eighth, segregation of duties; ninth, business constraints and conflicts such as suspended securities, overlapping event windows, scrub-set integrity, overlapping statement coverage, duplicate open claims, and account activity or settlement status; tenth, temporal windows judged against the logical clock; eleventh, referential eligibility such as voluntary-event checks, allowed election options, custodian-only statement sources, and claimable entitlements; and twelfth, fiscal caps such as the claim amount cap and the compensation pool reserve.

Resource existence is checked from the outside in. When a request path carries resource identifiers, identifiers are validated in left-to-right order, and the request is rejected with the not-found code of the first missing resource before body foreign keys are examined; body references are then checked in their declared field order. Each resource type has its own not-found error: `ERR_SECURITY_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_POSITION_LOT_NOT_FOUND`, `ERR_EVENT_SOURCE_NOT_FOUND`, `ERR_SOURCE_NOTIFICATION_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_ENTITLEMENT_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_BOOKING_LINE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CUSTODIAN_STATEMENT_NOT_FOUND`, and `ERR_RECON_BREAK_NOT_FOUND` — all HTTP 404. Malformed bodies — a missing required field, a type mismatch, or an invalid enumeration member — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Desk Setup: Securities, Accounts, and Tax Lots

Before any corporate action can be processed, the desk's static world must exist. A `DeskAdministrator` registers each tradeable instrument by supplying its `ticker`, its `cusip`, and a display `name`; the ticker and the CUSIP are each unique across all securities. A security begins life `ACTIVE`, and the administrator may later suspend it (`ACTIVE` → `SUSPENDED`) and reinstate it (`SUSPENDED` → `ACTIVE`) through a status update carrying the desired `status`. While a security is `SUSPENDED`, any attempt to create a new corporate action event for it is rejected with `ERR_SECURITY_SUSPENDED`. The securities listing can be filtered by `status`.

Client accounts are opened by the same role with an `account_number` (unique across accounts), a `holder_name`, and an optional `opening_cash_cents` that defaults to zero. At creation the account's `cash_balance_cents` is initialized to the opening amount, `total_cost_basis_cents` starts at zero, `pending_entitlement_count` starts at zero, and the account is `ACTIVE`. Day-to-day account status management belongs to the `OperationsManager`, who freezes an account (`ACTIVE` → `FROZEN`), restores it (`FROZEN` → `ACTIVE`), or closes it (`ACTIVE` → `CLOSED`, or `FROZEN` → `CLOSED`) by submitting the target `status`. Closing is guarded: an account with any `OPEN` position lot whose quantity is greater than zero, or any entitlement still in `PROJECTED` or `FIRM` status, cannot be closed and the attempt is rejected with `ERR_ACCOUNT_NOT_SETTLED`. Two later workflows depend on account status and are stated here once: an account that is not `ACTIVE` is skipped when an event is booked — its entitlement goes to `MISSED` — and an account that is not `ACTIVE` cannot submit elections. The accounts listing can be filtered by `status`.

Positions enter the system as desk-established tax lots. To establish a lot, a `DeskAdministrator` supplies the owning `account_id`, the held `security_id`, the `quantity`, the `acquisition_date`, and the lot's `cost_basis_total_cents`. The quantity must be greater than zero and expressed in no more than four decimal places; a non-positive quantity or one with finer precision is rejected with `ERR_LOT_QUANTITY_INVALID`. A desk-established lot is created with `origin_booking_id` null — that field is populated only on lots minted by a booking, where it points back at the booking that created them. Every lot starts `OPEN`, and the account's `total_cost_basis_cents` is recomputed as soon as the lot exists. When a booking or a reversal later drives a lot's quantity to exactly zero, the lot transitions `OPEN` → `FULLY_SURRENDERED` and no longer contributes to the account's cost basis total. The position-lot listing can be filtered by `account_id`, `security_id`, `origin_booking_id`, and `status`.

### 3.2. Announcement Sources and Raw Notification Intake

Corporate action news reaches the desk through registered sources. Registering a source takes a display `name` (a custodian feed, a vendor feed, and the like), a `source_type` of `CUSTODIAN`, `VENDOR`, or `DEPOSITORY`, and a `reliability_weight` — a non-negative integer expressing how much the desk trusts the source when announcements conflict. Higher weight wins; two sources of equal weight are disambiguated by which notification arrived first. Only `CUSTODIAN` sources may submit custody statements. The sources listing can be filtered by `source_type`.

Raw announcements are pushed into the system by a `VendorFeed`. Each notification names its `source_id` and the `security_id` it describes, declares an `event_type` of `SPLIT`, `MERGER`, `SPIN_OFF`, `CASH_DIVIDEND`, `STOCK_DIVIDEND`, or `RIGHTS_OFFERING`, states the announced `record_date`, and carries the source's `announced_terms` — the raw terms object exactly as the source published it. A notification is born `RECEIVED` and is immutable thereafter, carrying only its `id` and `created_at` as system fields. From `RECEIVED` a notification has exactly two exits: it is scrubbed into a golden event, moving to `MATCHED`, or an `EventAnalyst` judges it unusable and rejects it, moving it to `REJECTED`. The notifications listing can be filtered by `source_id`, `security_id`, and `status`.

### 3.3. Scrubbing: From Raw Notifications to a Golden Event

Scrubbing is the desk's act of editorial judgment: an `EventAnalyst` assembles at least two raw notifications into a single golden `CorporateActionEvent`. The creation payload names the subject `security_id`, the `event_type`, the scrubbed `terms` object, the `record_date`, and the `payable_date`, and identifies the scrub set via `source_notification_ids`. Optional fields govern the event's voluntary behavior and compensation policy: `election_required` (defaulting to false), `election_deadline`, `compensation_pool_cents` (defaulting to zero), and `claim_compensation_basis` (defaulting to `EVENT_TERMS`, with `MARKET_VALUE` as the alternative).

The scrub set must clear a precise bar, evaluated after the basic request-shape checks. It must contain at least two notifications; they must come from distinct sources; every one must still be `RECEIVED`; and they must agree with each other and with the request on security, event type, and record date. Finally, the submitted `terms` must equal the winning notification's `announced_terms`, where the winner is the notification from the source with the highest `reliability_weight`, ties broken in favor of the earliest notification `created_at`. Any shortfall — too few notifications, the same source twice, a notification not `RECEIVED`, a mismatch on security, type, or record date, or terms that diverge from the winner's announcement — is rejected with `ERR_NOTIFICATION_SCRUB_MISMATCH` (HTTP 409). On success, every referenced notification moves to `MATCHED`.

Two further guards protect the calendar. The security itself must be `ACTIVE`, else `ERR_SECURITY_SUSPENDED`. And a mandatory event — one with `election_required` false — must not collide with another live mandatory event on the same security: their half-open windows, from `record_date` inclusive to `payable_date` exclusive, must not overlap, though windows that merely touch at an endpoint are allowed. A collision is rejected with `ERR_EVENT_WINDOW_OVERLAP` (HTTP 409).

The `terms` object itself is validated for coherence with the declared `event_type`, and any incoherence — a missing required key, a zero denominator, a negative amount, an impossible date relationship — is rejected with `ERR_INVALID_EVENT_TERMS` (HTTP 400). The required keys per type are: `SPLIT` and `STOCK_DIVIDEND` carry `ratio_num`, `ratio_den`, `price_per_share_cents`, and `fractional_policy`; `MERGER` carries `cash_per_share_cents`, `cash_pool_cents`, `new_security_id`, `ratio_num`, `ratio_den`, and `default_option`; `SPIN_OFF` carries `spinoff_security_id`, `ratio_num`, `ratio_den`, `fmv_parent_cents`, `fmv_spin_cents`, `price_per_share_cents`, and `fractional_policy`; `CASH_DIVIDEND` carries `cash_per_share_cents`; and `RIGHTS_OFFERING` carries `rights_ratio_num`, `rights_ratio_den`, `subscription_price_cents`, `shares_offered`, and `oversubscription_allowed`. Ratio keys must be present with a denominator greater than zero, and required amounts must be non-negative. Dates must be self-consistent: the record date must not fall after the payable date; when `election_required` is true an `election_deadline` is mandatory and must fall no later than the end of the payable date's day; submissions are accepted while the logical clock is on or before that deadline.

A successfully scrubbed event is born `DRAFT`. The server records the scrubbing analyst as `scrubbed_by_user_id` and initializes `compensation_pool_remaining_cents` to the full `compensation_pool_cents`. The events listing can be filtered by `security_id`, `status`, and `event_type`.

### 3.4. Event Confirmation, Amendment, and Cancellation

A scrubbed event becomes operative through confirmation by a second `EventAnalyst` — never the same person, per the segregation-of-duties rule in §2.8. Confirmation moves `DRAFT` → `CONFIRMED`, stamps `confirmed_by_user_id` with the confirmer's identity, and increments the event's `version`. The moment an event is first confirmed, the system projects its entitlements: for every account holding at least one `OPEN` position lot in the event's security whose included position is greater than zero, a `PROJECTED` entitlement is created, and each affected account's `pending_entitlement_count` is recomputed.

Projection rests on a record-position snapshot with two basis variants, and the difference between them is the settlement lag. Under `TRADE_DATE_BASIS` — used for projections at confirm and amendment time — a lot is included when its `acquisition_date` falls on or before the record date, even if the trade would not have settled by then. Under `SETTLED_BASIS` — used when positions are firmed up at the record date — a lot is included only when its `acquisition_date` falls on or before two days before the record date, mirroring the market's settlement lag. In both variants the entitlement's `record_position_quantity` is the sum of the included lots' quantities at four decimal places, and identical inputs can therefore yield a smaller settled-basis position than the earlier trade-date projection.

From the snapshot, the projected quantities follow per event type. For ratio events (`SPLIT`, `STOCK_DIVIDEND`, `SPIN_OFF`), the ratio is the terms' `ratio_num` divided by `ratio_den`; the gross entitlement is the record position quantity multiplied by that ratio; `entitled_shares` is the gross rounded down to a whole share; `fractional_shares` is the remainder after removing that whole-share floor, rounded half-up to four decimal places; and `cash_in_lieu_cents` is the fractional shares multiplied by the terms' `price_per_share_cents`, rounded per the event's `fractional_policy`. For a `CASH_DIVIDEND`, `entitled_shares` and `fractional_shares` are both zero, and `cash_amount_cents` is the record position quantity rounded down to a whole share and multiplied by the terms' `cash_per_share_cents`. For a `RIGHTS_OFFERING`, `entitled_shares` is the record position quantity multiplied by the rights ratio — `rights_ratio_num` divided by `rights_ratio_den` — rounded down to a whole share, and `cash_amount_cents` is zero because exercise cash is debited at booking rather than credited. For a `MERGER`, both `entitled_shares` and `cash_amount_cents` are projected as zero, because merger outcomes depend on elections and are computed fully at booking. Each projected row is stamped with `calculation_basis` `TRADE_DATE_BASIS`. These aggregate projections are desk estimates; booking computes actuals per lot, and the two may legitimately differ on multi-lot accounts.

Terms change. An `EventAnalyst` applies an amendment by submitting `amended_terms` — a full replacement of the event's terms object — together with a free-text `reason` and the OCC field `expected_event_version` described in §2.7. Amendment requires the event to be `CONFIRMED`; against any other state the request fails the state check, with `ERR_EVENT_NOT_AMENDABLE` (HTTP 409) when the event is not in the amendable state. On success the event moves `CONFIRMED` → `AMENDED`, its `terms` are replaced, and its `version` increments by one. An immutable `EventAmendment` audit record is created pointing back to the event via `event_id`, stamped with `applied_by_user_id` and an `amendment_seq` equal to one plus the count of the event's prior amendments. The amendment also re-projects the world: every `PROJECTED` or `FIRM` entitlement of the event moves to `SUPERSEDED`, and for each superseded entitlement a replacement `PROJECTED` entitlement is created, recomputed on the new terms under `TRADE_DATE_BASIS` and linked to its predecessor through `supersedes_entitlement_id`. Affected accounts have their pending counts recomputed, with the accounts' `updated_at` and `version` bumped accordingly. An `AMENDED` event is confirmed again through the same confirmation path — `AMENDED` → `CONFIRMED`, with the same segregation-of-duties rule — but this second confirmation generates no entitlements, because the amendment already re-projected them; confirm does not duplicate them.

Cancellation is available from any non-terminal state and moves the event to `CANCELLED`. From `DRAFT` nothing exists yet to unwind. From `CONFIRMED` or `AMENDED`, cancellation supersedes every `PROJECTED` or `FIRM` entitlement (`PROJECTED` → `SUPERSEDED`, `FIRM` → `SUPERSEDED`) and voids every live election (`SUBMITTED` → `VOID`, `WITHDRAWN` → `VOID`), then recomputes each affected account's pending count. Once an event is `COMPLETED` or `CANCELLED` it is terminal: any further lifecycle operation against it is rejected with `ERR_EVENT_ALREADY_TERMINAL` (HTTP 409). The amendments applied to an event remain listable as a permanent audit trail.

### 3.5. Voluntary Elections and the Election Deadline

Two event types ask the client a question. A voluntary `MERGER` offers a choice between `CASH` and `STOCK`; a `RIGHTS_OFFERING` invites the holder to `EXERCISE`. The client's answer is an `Election`, submitted by the `AccountHolder` role, and every guard below is evaluated in the global order of §2.10 — ownership before state, state before the OCC version match, and so on.

Submission names the `account_id` the election is for, the chosen `option_code`, the OCC field `expected_event_version`, and — for rights only — a `quantity`. The ownership rule is absolute: the caller's `X-User-ID` must equal the election's `account_id`, otherwise the request is rejected with `ERR_ACCOUNT_OWNERSHIP_MISMATCH` (HTTP 403). The account must be `ACTIVE`; otherwise `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409). The event must be `CONFIRMED` — an election against an event in any other state is rejected with `ERR_EVENT_NOT_ACCEPTING_ELECTIONS` — and it must actually be voluntary, else `ERR_EVENT_NOT_VOLUNTARY` (HTTP 422). The logical clock must be on or before the event's `election_deadline`; a submission strictly after the deadline is rejected with `ERR_ELECTION_DEADLINE_PASSED` (HTTP 422). The supplied `expected_event_version` must match the event's current `version`, else `ERR_STALE_EVENT_VERSION` (HTTP 412) per §2.7 — an election supersedes the account's prior submission, so it must be made against the terms and deadline the desk currently holds, not a stale copy.

Option validity is type-scoped: a `MERGER` accepts `CASH` or `STOCK`, a `RIGHTS_OFFERING` accepts `EXERCISE`, and `quantity` is required for a rights election and forbidden for any other type; violations are rejected with `ERR_INVALID_ELECTION_OPTION` (HTTP 400). When the rights event's `oversubscription_allowed` is false, the requested `quantity` must not exceed the account's entitled rights; an excess request is rejected with `ERR_ELECTION_QUANTITY_EXCEEDS_ENTITLEMENT` (HTTP 422).

A submitted election is born `SUBMITTED`, stamped with the logical-clock instant as `submitted_at`, and numbered with an `election_seq` equal to one plus the count of prior elections by that account on that event across all statuses. Submission is also replacement: any other `SUBMITTED` election by the same account on the same event moves to `SUPERSEDED`. Every submission, withdrawal, and resubmission increments the hosting event's `version` by one — which is precisely what makes a stale `expected_event_version` detectable on the next write.

The election lifecycle is cyclic while the window is open. The holder may withdraw a live election (`SUBMITTED` → `WITHDRAWN`) and later resubmit it (`WITHDRAWN` → `SUBMITTED`); resubmission refreshes `submitted_at`, increments `election_seq`, and supersedes any other `SUBMITTED` election the account has on the event. Withdrawal requires a `SUBMITTED` election and resubmission a `WITHDRAWN` one; attempting either against the wrong state is rejected with `ERR_ELECTION_INVALID_STATE` (HTTP 409). Both actions enforce the same ownership rule and the same inclusive deadline as submission, and resubmission additionally requires the event to be `CONFIRMED`. Three system-driven exits close the lifecycle at booking or cancellation time: the latest `SUBMITTED` election per account is applied at booking (`SUBMITTED` → `APPLIED`), a `WITHDRAWN` election lapses when the event is booked with no live election from that account (`WITHDRAWN` → `LAPSED`), and both `SUBMITTED` and `WITHDRAWN` elections are voided when the event is cancelled. The elections listing can be filtered by `event_id`, `account_id`, and `status`.

### 3.6. Record-Date Capture and Event Booking

Projection gives the desk an estimate; the record date makes it firm. Once the logical clock has reached midnight UTC at the start of the event's record date, the `OperationsManager` may capture the record position. Attempting capture earlier is rejected with `ERR_RECORD_DATE_NOT_REACHED` (HTTP 422), and capture requires a `CONFIRMED` event, else `ERR_EVENT_NOT_CONFIRMED` (HTTP 409). Capture recomputes every `PROJECTED` entitlement in place under `SETTLED_BASIS` — `record_position_quantity`, `entitled_shares`, `fractional_shares`, `cash_in_lieu_cents`, and `cash_amount_cents` are all overwritten with the settled-basis figures, `calculation_basis` becomes `SETTLED_BASIS`, and the entitlement moves `PROJECTED` → `FIRM` with its `version` incremented.

Booking is the point of no return, performed by the `OperationsManager`. Like capture, it requires a `CONFIRMED` event — an attempt against an event in any other state is rejected with `ERR_EVENT_NOT_CONFIRMED` — and it is guarded twice more: every non-`SUPERSEDED` entitlement of the event must be `FIRM` — a still-`PROJECTED` entitlement blocks booking with `ERR_ENTITLEMENTS_NOT_FIRM` — and for a voluntary event the logical clock must be strictly after the `election_deadline`, since booking at or before the deadline is rejected with `ERR_ELECTION_WINDOW_OPEN` (HTTP 422). On success the event moves `CONFIRMED` → `BOOKED` and its `version` increments.

The booking cascade touches five linked chains, all visible in the same response. First, a `Booking` is created in `POSTED` status, linked to the event via `event_id` and stamped with the operator's identity as `booked_by_user_id` and the logical-clock instant as `booked_at`. Second, each `FIRM` entitlement settles or misses: when its account is `ACTIVE` the entitlement moves `FIRM` → `SETTLED`; when the account is not `ACTIVE` it moves `FIRM` → `MISSED`, and no lot is mutated and no cash is credited for it. In the same pass, elections resolve — the latest `SUBMITTED` election per account becomes `APPLIED`, and any `WITHDRAWN` election becomes `LAPSED`. Third, each settled entitlement drives the per-type booking algorithm below, mutating or creating position lots and posting immutable `BookingLine` ledger records. Fourth, every affected account's `cash_balance_cents`, `total_cost_basis_cents`, and `pending_entitlement_count` are recomputed per §2.9. Fifth, every `OPEN` reconciliation break of type `POSITION_MISMATCH` whose account and security now match the internal books is automatically resolved with `resolution` `AUTO_BOOKING`.

Each `BookingLine` records its `booking_id`, the `entitlement_id` it settles, the `position_lot_id` it mutates or creates (null on pure-cash lines), a `line_kind` of `LOT_MUTATION`, `LOT_CREATION`, `CASH_CREDIT`, `CASH_DEBIT`, or `CASH_IN_LIEU`, and three signed deltas: `quantity_delta` for the share change (zero on cash lines), `basis_delta_cents` for the cost-basis change (zero on cash lines), and `cash_delta_cents` for the account cash movement (zero on lot lines). Crucially, every lot line also stores `prior_quantity` and `prior_basis_cents` — the lot's values immediately before the line — which is what later makes an exact, recompute-free reversal possible.

The per-type algorithms run per account, over that account's `OPEN` lots in the event security, processing lots in `acquisition_date` ascending order with ties broken by `created_at` ascending.

For a `SPLIT` or `STOCK_DIVIDEND`, booking applies the per-lot floor-then-sum rule, and the pinned rounding order is load-bearing. For each lot in order: the exact entitlement is the lot's quantity multiplied by the ratio (`ratio_num` divided by `ratio_den`); the whole-share part is that exact value rounded down; the lot's fractional part is the exact value minus that floor; and the lot's quantity is set to the whole-share part at four decimal places. After all lots are processed, the account's fractional position is the sum of the per-lot fractional parts, rounded half-up to four decimal places; the entitlement's `booked_whole_shares` is the sum of the per-lot whole-share floors; and its `booked_cash_in_lieu_cents` is the account fractional position multiplied by the terms' `price_per_share_cents`, rounded per the event's `fractional_policy` as defined in §2.6. Cost basis is conserved in total: a split or stock dividend leaves each lot's `cost_basis_total_cents` unchanged, because per-share basis is derived and never stored. A lot whose quantity reaches exactly zero becomes `FULLY_SURRENDERED`.

For a `SPIN_OFF`, booking both distributes shares of the spin-off company and splits each parent lot's cost basis between parent and spin-off. The basis split percentage is the terms' `fmv_spin_cents` divided by the sum of `fmv_parent_cents` and `fmv_spin_cents`, rounded half-up to four decimal places before any lot is touched. Then, per lot in the pinned order: the spin lot's basis is the parent lot's `cost_basis_total_cents` multiplied by that percentage, rounded half-up to whole cents; the parent keeps the remainder, so the parent lot's basis becomes its old basis minus the spin lot's basis — conservation is exact per lot, with no drift. A new spin-co lot is created whose quantity is the parent lot's quantity multiplied by the ratio, rounded down to a whole share, whose `cost_basis_total_cents` is the spin basis just computed, whose `acquisition_date` is inherited from the parent lot, and whose `origin_booking_id` points to this booking. Fractional spin-co shares are cashed in lieu at the terms' `price_per_share_cents` following the same per-lot floor-then-sum rule as a split.

For a voluntary `MERGER` booked after its deadline, cash is scarce and allocation follows a pinned waterfall. Accounts are first classified: an odd-lot account holds more than zero and fewer than 100 shares of settled position. Odd-lot accounts that elected `CASH` are honored in full first, at their shares multiplied by the terms' `cash_per_share_cents`; if that total alone exceeds the terms' `cash_pool_cents`, the odd-lot cash electors are prorated among themselves in shares-descending order, ties broken by the election's `created_at` ascending, so the pool never goes negative. The remaining pool — the original pool minus what odd-lot electors received — then funds round-lot cash elections. The proration factor is the smaller of one and the quotient of the remaining pool divided by the total round-lot cash elected (the sum over round-lot `CASH` electors of shares multiplied by `cash_per_share_cents`), with that quotient rounded down to four decimal places; when no round-lot cash was elected, the factor is zero. Each round-lot cash elector then receives cash for its shares multiplied by the factor, rounded down to whole shares, paid at `cash_per_share_cents`; its remaining shares convert into the new security at the terms' ratio, floored per lot with cash-in-lieu on the fractional remainders exactly as in a split. Accounts that elected `STOCK`, and accounts with no live election — which follow the terms' `default_option` — convert fully into the new security. Lots minted by a merger stock leg take the event's `payable_date` as their `acquisition_date`. Any pool left over is retained by the desk; there is no redistribution pass.

For a `RIGHTS_OFFERING`, allocation resolves an apparently circular dependency — each oversubscription depends on the pool remainder, which depends on all allocations — by pinning a single evaluation pass. Each `EXERCISE` election first receives its basic allocation: the smaller of its requested `quantity` and its entitled rights. The exercised total is the sum of those basics, and the remainder is the terms' `shares_offered` minus the exercised total, floored at zero. Oversubscribers are the accounts whose requested quantity exceeds their entitled rights, and only when the terms' `oversubscription_allowed` is true. Each oversubscriber's excess allocation is the smaller of its requested excess and its proportional share of the remainder — the remainder multiplied by its entitled rights and divided by the total entitled rights across all oversubscribers — rounded down to whole shares, and zero when that denominator is zero. The final allocation is basic plus excess, and the account is debited its allocation multiplied by the terms' `subscription_price_cents`; the debit may push the account's cash negative, which the desk settles externally. Exactly one proration pass runs — whatever remains unallocated after it is retained by the issuer. Lots created by a rights exercise take the event's `payable_date` as their `acquisition_date`.

A `CASH_DIVIDEND` booking mutates no lots: each settled entitlement simply credits its `cash_amount_cents` to the account as a cash-credit line.

The booking's three totals summarize the cascade: `total_whole_shares_credited` is the sum of whole shares credited across all `SETTLED` entitlements in the booking; `total_cash_credited_cents` is the sum of every cash credit — dividends and merger cash legs — with rights debits excluded; and `total_cash_in_lieu_cents` is the sum of booked cash-in-lieu across the booking. Entitlements that settled carry their realized figures in `booked_whole_shares` and `booked_cash_in_lieu_cents`, which remain null on any entitlement that has not settled. The bookings of an event are listable, as are individual bookings and ledger lines; the booking-lines listing can be filtered by `booking_id`, `position_lot_id`, and `entitlement_id`, and the entitlements listing by `event_id`, `account_id`, `status`, and `supersedes_entitlement_id`.

### 3.7. Booking Reversal and Event Completion

A posted booking can be undone — but only exactly, and only while nothing downstream depends on it. Reversal, performed by the `OperationsManager`, requires the booking to be `POSTED` and no `PAID` claim to reference any entitlement the booking settled; otherwise the request is rejected with `ERR_BOOKING_NOT_REVERSIBLE` (HTTP 409). On success the booking moves `POSTED` → `REVERSED`, and every one of its lines is inverted using the recorded `prior_quantity` and `prior_basis_cents` — an exact restore, never a recompute. Lots that the booking created move to `FULLY_SURRENDERED` with quantity zero; entitlements the booking settled return from `SETTLED` to `FIRM` with `booked_whole_shares` and `booked_cash_in_lieu_cents` reset to null; entitlements that went `MISSED` stay `MISSED`. Every affected account's cash, cost basis, and pending count is recomputed, and the event itself returns from `BOOKED` to `CONFIRMED` with its `version` incremented — ready, if needed, to be amended and booked again.

Completion closes the event's lifecycle. The `OperationsManager` completes a `BOOKED` event — completion against any other state fails the state check, with `ERR_EVENT_NOT_BOOKED` (HTTP 409) when the event is not booked — and two gates apply: every non-`SUPERSEDED` entitlement must be in `SETTLED` or `COMPENSATED`, else `ERR_UNSETTLED_ENTITLEMENTS_EXIST` (HTTP 409), and no `OPEN` reconciliation break may reference the event, else `ERR_OPEN_RECON_BREAKS_EXIST` (HTTP 409). Completion moves the event `BOOKED` → `COMPLETED` and increments its `version`. `COMPLETED` and `CANCELLED` are the event's terminal states.

### 3.8. Compensation Claims

When an entitlement goes missing or is booked for the wrong amount, the client files a claim. Filing is an `AccountHolder` action and names the `event_id`, the `entitlement_id`, the `account_id`, a `reason` of `MISSED_ENTITLEMENT`, `INCORRECT_AMOUNT`, or `FRACTIONAL_DISPUTE`, the asserted `claimed_amount_cents`, and — when the event's compensation basis calls for it — a `market_price_cents`. The ownership rule of §3.5 applies unchanged: the caller's `X-User-ID` must equal the claim's `account_id`, else `ERR_ACCOUNT_OWNERSHIP_MISMATCH`. The claimed amount must be greater than zero and no more than 250,000 cents; anything else is rejected with `ERR_CLAIM_AMOUNT_EXCEEDS_CAP` (HTTP 422). The named entitlement must belong to the same event and the same account as the claim, and must be in `MISSED` or `SETTLED` status; otherwise the filing is rejected with `ERR_ENTITLEMENT_NOT_CLAIMABLE` (HTTP 422). At most one open claim may exist per entitlement: if another `FILED` claim already references it, the filing is rejected with `ERR_DUPLICATE_OPEN_CLAIM` (HTTP 409). And the window is bounded — a claim must be filed while the logical clock is no later than thirty days after the event's `payable_date`, inclusive of that final day; a later filing is rejected with `ERR_CLAIM_WINDOW_EXPIRED` (HTTP 422). A claim is born with `review_status` `FILED` and `payment_status` `UNPAID` — two independent dimensions — and the server records the filer as `filed_by_user_id` (the literal value "system" for claims the reconciliation engine files automatically, as §3.9 describes).

Decision belongs to the `ClaimsExaminer`, who submits a `decision` of `APPROVED` or `DENIED`. The checks run in order: the claim must still be `FILED`, else `ERR_CLAIM_NOT_FILED` (HTTP 409); then segregation of duties — the examiner's `X-User-ID` must differ from `filed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; then, for an approval only, pool sufficiency. The examiner's identity is recorded as `reviewed_by_user_id` on either outcome.

Approval computes and stores `compensation_cents` — null on the claim until this point — according to the event's `claim_compensation_basis`. Under the `EVENT_TERMS` variant, compensation is the entitlement's `cash_amount_cents`, plus its `entitled_shares` valued at the event terms' `price_per_share_cents` — zero when the terms carry no per-share price — plus its `cash_in_lieu_cents`. Under the `MARKET_VALUE` variant, the same three components apply but the shares are valued at the claim's `market_price_cents` supplied at filing, which is why that field is required when the event's basis is `MARKET_VALUE`. The same entitlement therefore yields different compensation when the terms price and the filing-time market price differ. The computed compensation must fit within the event's `compensation_pool_remaining_cents`; if it exceeds the remaining pool the approval is rejected with `ERR_COMPENSATION_POOL_EXHAUSTED` (HTTP 402). On a successful approval the pool's remaining amount is decremented by the compensation — the money is reserved at approval time — and the event's `version` increments.

Payment is the final step and belongs to the `OperationsManager`. It requires the claim to be `APPROVED` and still `UNPAID`; anything else is rejected with `ERR_CLAIM_NOT_PAYABLE` (HTTP 409). Payment moves `payment_status` from `UNPAID` to `PAID`, credits the claim's `compensation_cents` to the account's `cash_balance_cents` with the account's `updated_at` and `version` bumped, and — when the claimed entitlement is `MISSED` — moves that entitlement to `COMPENSATED`, its terminal state. The claims listing can be filtered by `event_id`, `entitlement_id`, `account_id`, and `review_status`.

### 3.9. Custodian Statements, Reconciliation, and Break Resolution

The desk's books are only as good as their agreement with the custodian's. A `CustodianFeed` submits a statement naming its `source_id` — which must reference a `CUSTODIAN`-type source, else `ERR_SOURCE_NOT_CUSTODIAN` (HTTP 422) — together with a `coverage_start_date`, a `coverage_end_date`, and the statement `lines`. The coverage window is a closed interval, inclusive of both days, so the start must not fall after the end — an inverted window fails request-shape validation with `ERR_INVALID_REQUEST` — and two statements from the same source must not share even a single day; an overlapping submission is rejected with `ERR_STATEMENT_COVERAGE_OVERLAP` (HTTP 409). Each line carries an `account_id`, a `security_id`, a `quantity`, and optionally `cash_cents` and an `event_id`: the presence of `event_id` marks the line as an entitlement reconciliation for that event, its absence marks a position reconciliation, and a `cash_cents` value alongside an `event_id` marks a cash reconciliation for that event.

Reconciliation runs synchronously inside ingestion: the statement is created, every line is checked top-to-bottom in the order submitted, breaks are created, and the create response already shows the statement `RECONCILED` (having briefly been `RECEIVED`). The comparison is zero-tolerance — exact equality is the only outcome that raises no break. A position line is compared against the sum of quantities over the account's `OPEN` lots in that security, at four decimal places; any difference creates a `POSITION_MISMATCH` break. An entitlement line is compared against the `entitled_shares` of the non-`SUPERSEDED` entitlement for that event and account; any difference creates a `MISSED_ENTITLEMENT` break — and when that entitlement is `MISSED` or `SETTLED` and no `FILED` claim exists for it, the engine automatically files a claim on the client's behalf, with `filed_by_user_id` recorded as "system" and a `claimed_amount_cents` equal to the absolute difference between expected and reported shares, valued under the event's `EVENT_TERMS` compensation basis. A cash line is compared against the sum of `cash_delta_cents` over `POSTED` booking lines for that event and account; any difference creates a `CASH_MISMATCH` break carrying both the internal `expected_cash_cents` and the custodian's `reported_cash_cents`.

Every `ReconBreak` records its `statement_id`, the `account_id` and `security_id` in question, a `break_type` of `POSITION_MISMATCH`, `CASH_MISMATCH`, or `MISSED_ENTITLEMENT`, and the quantities on both sides of the mismatch as `expected_quantity` and `reported_quantity` at four decimal places. The `event_id` is set on `MISSED_ENTITLEMENT` and `CASH_MISMATCH` breaks and null otherwise; the cash figures are set only on `CASH_MISMATCH` breaks. When an auto-claim was filed, the break's `auto_claim_id` links to it; the field stays null when auto-filing was suppressed or not applicable. A break is born `OPEN` with `resolution` null.

Breaks leave `OPEN` by two doors. The booking cascade of §3.6 resolves position breaks automatically when books and statement come back into agreement, stamping `resolution` `AUTO_BOOKING`. Manually, an `OperationsManager` resolves a break by submitting a `resolution` of `RESOLVED` or `WRITTEN_OFF` together with a `resolution_note`; the break must be `OPEN`, else `ERR_RECON_BREAK_NOT_OPEN` (HTTP 409), and the note is required on both manual paths — omitting it fails request-shape validation with `ERR_INVALID_REQUEST`. A manual resolution stores `resolution` `MANUAL` and moves the break `OPEN` → `RESOLVED`; a write-off stores `WRITTEN_OFF` and moves it `OPEN` → `WRITTEN_OFF`. The breaks listing can be filtered by `statement_id`, `event_id`, `account_id`, `security_id`, `break_type`, `status`, and `auto_claim_id`; the statements listing by `source_id` and `status`.

## 4. Endpoint Definitions

Operations that create a new resource — a security, an account, a position lot, an event source, a source notification, an event, an amendment, a booking, an election, a claim, or a custodian statement — return `201 Created`. Operations that modify an existing resource or drive a state transition — confirmation, cancellation, capture, completion, reversal, withdrawal, resubmission, decision, payment, resolution, status updates, and setting the clock — return `200 OK`, as do all retrieval and listing endpoints.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock | DeskAdministrator |
| POST | `/api/securities` | Register a security | DeskAdministrator |
| GET | `/api/securities` | List securities | All roles |
| GET | `/api/securities/{id}` | Get a security | All roles |
| PUT | `/api/securities/{id}` | Suspend or reinstate a security | DeskAdministrator |
| POST | `/api/accounts` | Open a client account | DeskAdministrator |
| GET | `/api/accounts` | List accounts | All roles |
| GET | `/api/accounts/{id}` | Get an account | All roles |
| PUT | `/api/accounts/{id}` | Freeze, unfreeze, or close an account | OperationsManager |
| POST | `/api/position-lots` | Establish a tax lot (desk-side position entry) | DeskAdministrator |
| GET | `/api/position-lots` | List position lots | All roles |
| GET | `/api/position-lots/{id}` | Get a position lot | All roles |
| POST | `/api/event-sources` | Register an event notification source | DeskAdministrator |
| GET | `/api/event-sources` | List event sources | All roles |
| GET | `/api/event-sources/{id}` | Get an event source | All roles |
| POST | `/api/source-notifications` | Ingest a raw event notification from a source | VendorFeed |
| GET | `/api/source-notifications` | List source notifications | All roles |
| GET | `/api/source-notifications/{id}` | Get a source notification | All roles |
| POST | `/api/source-notifications/{id}/reject` | Reject a received notification as unusable | EventAnalyst |
| POST | `/api/events` | Scrub raw notifications into a golden corporate action event (DRAFT) | EventAnalyst |
| GET | `/api/events` | List corporate action events | All roles |
| GET | `/api/events/{id}` | Get an event | All roles |
| POST | `/api/events/{id}/confirm` | Confirm a scrubbed event (second analyst; generates PROJECTED entitlements) | EventAnalyst |
| POST | `/api/events/{id}/amendments` | Apply a terms amendment to a CONFIRMED event (OCC-guarded) | EventAnalyst |
| GET | `/api/events/{id}/amendments` | List amendments of an event | All roles |
| POST | `/api/events/{id}/cancel` | Cancel a non-terminal event | EventAnalyst |
| POST | `/api/events/{id}/capture-record-position` | Firm up entitlements at record date under SETTLED_BASIS | OperationsManager |
| POST | `/api/events/{id}/book` | Book the event: settle entitlements, apply elections, mutate lots, credit cash, auto-resolve position breaks | OperationsManager |
| GET | `/api/events/{id}/bookings` | List bookings of an event | All roles |
| POST | `/api/events/{id}/complete` | Complete a booked event once entitlements terminal and breaks resolved | OperationsManager |
| GET | `/api/bookings/{id}` | Get a booking | All roles |
| POST | `/api/bookings/{id}/reverse` | Reverse a posted booking (exact restore from line prior values) | OperationsManager |
| GET | `/api/booking-lines` | List booking lines | All roles |
| GET | `/api/booking-lines/{id}` | Get a booking line | All roles |
| POST | `/api/events/{id}/elections` | Submit (or supersede) a voluntary election for an account (OCC-guarded) | AccountHolder |
| POST | `/api/elections/{id}/withdraw` | Withdraw a submitted election before the deadline | AccountHolder |
| POST | `/api/elections/{id}/resubmit` | Resubmit a withdrawn election before the deadline | AccountHolder |
| GET | `/api/elections` | List elections | All roles |
| GET | `/api/elections/{id}` | Get an election | All roles |
| POST | `/api/claims` | File a compensation claim for a missed or mis-booked entitlement | AccountHolder |
| GET | `/api/claims` | List claims | All roles |
| GET | `/api/claims/{id}` | Get a claim | All roles |
| POST | `/api/claims/{id}/decide` | Approve (computes compensation, reserves pool) or deny a claim | ClaimsExaminer |
| POST | `/api/claims/{id}/pay` | Pay an approved claim (credits account, compensates MISSED entitlement) | OperationsManager |
| POST | `/api/custodian-statements` | Ingest a custodian statement; reconciliation runs synchronously and breaks are created | CustodianFeed |
| GET | `/api/custodian-statements` | List custodian statements | All roles |
| GET | `/api/custodian-statements/{id}` | Get a custodian statement | All roles |
| GET | `/api/recon-breaks` | List reconciliation breaks | All roles |
| GET | `/api/recon-breaks/{id}` | Get a recon break | All roles |
| POST | `/api/recon-breaks/{id}/resolve` | Manually resolve or write off an open break | OperationsManager |
| GET | `/api/entitlements` | List entitlements | All roles |
| GET | `/api/entitlements/{id}` | Get an entitlement | All roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_EVENT_TERMS` | 400 Bad Request |
| `ERR_LOT_QUANTITY_INVALID` | 400 Bad Request |
| `ERR_SECURITY_NOT_FOUND` | 404 Not Found |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_POSITION_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_SOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_SOURCE_NOTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_ENTITLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ELECTION_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTODIAN_STATEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RECON_BREAK_NOT_FOUND` | 404 Not Found |
| `ERR_ACCOUNT_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_EVENT_NOT_CONFIRMED` | 409 Conflict |
| `ERR_EVENT_NOT_AMENDABLE` | 409 Conflict |
| `ERR_EVENT_NOT_BOOKED` | 409 Conflict |
| `ERR_EVENT_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_EVENT_NOT_ACCEPTING_ELECTIONS` | 409 Conflict |
| `ERR_ELECTION_INVALID_STATE` | 409 Conflict |
| `ERR_CLAIM_NOT_FILED` | 409 Conflict |
| `ERR_CLAIM_NOT_PAYABLE` | 409 Conflict |
| `ERR_BOOKING_NOT_REVERSIBLE` | 409 Conflict |
| `ERR_RECON_BREAK_NOT_OPEN` | 409 Conflict |
| `ERR_UNSETTLED_ENTITLEMENTS_EXIST` | 409 Conflict |
| `ERR_OPEN_RECON_BREAKS_EXIST` | 409 Conflict |
| `ERR_ENTITLEMENTS_NOT_FIRM` | 409 Conflict |
| `ERR_SECURITY_SUSPENDED` | 409 Conflict |
| `ERR_EVENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_STATEMENT_COVERAGE_OVERLAP` | 409 Conflict |
| `ERR_NOTIFICATION_SCRUB_MISMATCH` | 409 Conflict |
| `ERR_DUPLICATE_OPEN_CLAIM` | 409 Conflict |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_SETTLED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_STALE_EVENT_VERSION` | 412 Precondition Failed |
| `ERR_RECORD_DATE_NOT_REACHED` | 422 Unprocessable Entity |
| `ERR_ELECTION_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_ELECTION_WINDOW_OPEN` | 422 Unprocessable Entity |
| `ERR_CLAIM_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_EVENT_NOT_VOLUNTARY` | 422 Unprocessable Entity |
| `ERR_INVALID_ELECTION_OPTION` | 400 Bad Request |
| `ERR_SOURCE_NOT_CUSTODIAN` | 422 Unprocessable Entity |
| `ERR_ENTITLEMENT_NOT_CLAIMABLE` | 422 Unprocessable Entity |
| `ERR_CLAIM_AMOUNT_EXCEEDS_CAP` | 422 Unprocessable Entity |
| `ERR_COMPENSATION_POOL_EXHAUSTED` | 402 Payment Required |
| `ERR_ELECTION_QUANTITY_EXCEEDS_ENTITLEMENT` | 422 Unprocessable Entity |
