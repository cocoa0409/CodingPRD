# Youth Org Troop Mgmt API — Product Requirements Document

## 1. Introduction

Local youth-scouting councils carry an administrative burden that grows quietly but relentlessly across a program year: youth and adult members must be registered and kept current on dues, leaders must clear background checks and youth-protection training before they can be counted toward a charter, scouts advance through ranks and merit badges that demand a documented sign-off trail, campouts require permission slips and health forms that no one can locate the night before departure, and the autumn cookie-and-popcorn fundraiser turns every troop into a small inventory-and-cash operation that the council must reconcile to the penny. This API is the system of record that ties those threads together for an organization modeled on Scouts BSA and Girl Scouts practice.

The platform is built around a strict Council → Troop → Member tree, overlaid with cross-cutting fundraisers, events, and a council fund ledger that routes money between troop dues accounts, council cash, and supplier liability. Two operator roles share the work under a deliberate segregation of duties: the council registrar who owns chartering, background-check resolution, and advancement approval, and the troop leader who runs the day-to-day of members, advancements, events, and product sales. Because rechartering depends on derived counts that any number of small operations can quietly change, and because fund balances must always reconcile, the system treats consistency and auditability as first-class concerns: derived gates recompute immediately, optimistic concurrency guards the highest-stakes writes, and every dollar that moves leaves a ledger row behind it.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and contractual boilerplate that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the operational capacity under which they are acting. The system recognizes exactly two roles, spelled precisely as `CouncilRegistrar` and `TroopLeader`. If either header is missing, or if `X-User-Role` does not name a known role, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Both roles are operator roles whose identity is opaque: when `X-User-Role` is `CouncilRegistrar`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity, and likewise when `X-User-Role` is `TroopLeader` the `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records these identifiers where a workflow demands it — for example, it captures the opening operator's id as `requested_by_user_id` on a `LeaderCredential` when a leader credential is opened, and it stamps the submitting operator's id as `submitted_by_user_id` on an `Advancement` when an advancement is submitted — but it never compares `X-User-ID` to any entity's `id` for ownership. Those two recorded identifiers exist solely to anchor the segregation-of-duties checks described later: the same operator may not both request and resolve a background check, and the same operator may not both submit and approve an advancement.

The `CouncilRegistrar` exclusively owns council creation, troop creation, fundraiser creation, the three troop charter-lifecycle transitions (recharter, lapse, drop), all background-check operations, training completion, advancement return and approval, taking a fundraiser live and closing it, the council ledger and reporting reads, and advancing the test clock. The `TroopLeader` exclusively owns member suspension, reinstatement, and dropping, opening leader credentials, creating advancements and signing their requirements and submitting them, all event and event-registration operations, placing/filling/cancelling fundraiser orders, and reserving and releasing booths. Member registration, issuing a dues invoice, and posting a payment are shared operations available to both roles, as are all read (GET) endpoints.

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

### 2.4. Common Resource Properties and System-Managed Fields

Most resources in this system carry a common set of system-managed fields. Every such resource exposes an `id` formatted as a UUID with no type prefix, a `created_at` timestamp, and an `updated_at` timestamp; both timestamps are ISO 8601 instants in UTC rendered with three fractional digits. Most resources also expose a `version`, a system-managed integer that begins at 1 on creation and increases by one on every mutation; it underpins the optimistic concurrency control described in §2.6.

Two entities are deliberate exceptions that carry **only** `id` and `created_at` — they have neither an `updated_at` nor a `version`, because each is an append-only, write-once record. The first is the `Payment`: once posted it is never edited or reversed (its `status` is permanently `POSTED`, and any unwinding of money happens through a separate reversal ledger row, never by mutating the payment). The second is the `FundLedgerEntry`, the immutable accounting row of the fund ledger. Both are written once and read thereafter; neither ever takes a `version`.

Among the `version`-bearing entities, only two participate in optimistic concurrency: the `Troop` carries a `version` that the recharter write checks, and the `Fundraiser` carries a `version` that the order-placement write checks. Other entities such as `Member`, `LeaderCredential`, `Advancement`, `Event`, `EventRegistration`, `DuesInvoice`, `FundraiserOrder`, `BoothReservation`, and `Council` carry a `version` for audit and lost-update purposes, but no endpoint requires a client-supplied expected version for them.

### 2.5. Derived Counts, Recharter Posture, and Hierarchical Recomputation

A defining characteristic of this system is that a `Troop` advertises several **computed** fields that no client ever writes directly — they are recomputed from the troop's children and its ledger whenever those children change. The `registered_youth_count` is the number of members in the troop whose `member_type` is `YOUTH` and whose `registration_status` is `REGISTERED`. The `cleared_leader_count` is the number of adult members in the troop (those with `member_type` of `ADULT`) who hold a `LeaderCredential` whose `bgcheck_status` is `CLEARED` and whose `training_status` is `TRAINED` — both dimensions must be satisfied for a leader to count. The `dues_account_cents` is the troop's held dues balance, computed as the sum of `amount_cents` across every `FundLedgerEntry` whose `account` is `TROOP_DUES` and whose `troop_id` matches the troop.

From the two head-count fields the system derives the `recharter_posture`, a compound gate that takes one of three values. It is `READY` only when the troop has at least 5 registered youth and at least 2 cleared-and-trained leaders (the pinned minimums are five youth and two leaders). When either head count falls short, the posture is `BLOCKED`. Independently of the head counts, once the troop's `charter_expires_at` instant lies strictly before the current logical clock time, the posture becomes `EXPIRED`. Newly created troops therefore begin with a `BLOCKED` posture, since a fresh troop has no registered youth or cleared leaders yet.

Because these derived fields cross the parent-child boundary, the system recomputes them eagerly and propagates the result upward. Any operation that registers, suspends, reinstates, or drops a member; resolves a background check or completes training on a leader credential; or places, cancels, or fills a fundraiser order that moves money into or out of `TROOP_DUES` will recompute the affected `registered_youth_count`, `cleared_leader_count`, `recharter_posture`, and `dues_account_cents`, refresh the troop's `updated_at`, and increment the troop's `version` by one. This eager bump is intentional: it is precisely why a recharter request that carries a now-stale expected version fails its concurrency check (see §2.6). When any of these read endpoints — getting a single troop, a single fundraiser, a member, an event, or a council — is invoked, the corresponding derived counts and balances are recomputed on read so that what is returned always reflects current reality.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and for those two the version field is **not** optional. Rechartering a troop requires the request body to carry `expected_troop_version`, which must equal the target troop's current `version` at the moment the write is processed. Because a background-check clearance, a member drop, a dues payment, or any of the other child-driven recomputations described in §2.5 can advance the troop's `version` between the time a client reads the posture and the time it submits the recharter, a request whose `expected_troop_version` no longer matches is rejected with `ERR_STALE_VERSION` (HTTP 412). This forces the operator to re-read the troop's posture before committing the charter rather than acting on a stale view.

Symmetrically, placing a fundraiser order requires the request body to carry `expected_fundraiser_version`, which must equal the target fundraiser's current `version`. Every go-live, order placement, and order cancellation recomputes the fundraiser's `allocated_units` and `available_units` and increments its `version`; a placement request whose `expected_fundraiser_version` no longer matches the fundraiser's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), so a seller must re-read available inventory before committing an allocation. No other endpoint takes an expected-version field, and supplying one elsewhere has no concurrency effect.

### 2.7. Nested Path Validation and Referential Integrity

When an endpoint path contains more than one resource identifier, the system validates them strictly left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not name an existing resource — the council is checked before the troop, the troop before the member, and so on down the path. This ordering guarantees that an operation on a child can never silently proceed inside a non-existent parent.

Beyond path identifiers, several create operations carry foreign keys in the request body. When placing a fundraiser order, registering an event participant, posting a payment, or reserving a booth, every body-level reference — `member_id`, `troop_id`, `seller_member_id`, `invoice_id`, `event_id`, or `fundraiser_id`, as applicable — must name an existing row, and additionally the `seller_member_id` on an order must belong to the same troop named by the order's `troop_id`. A violation of either condition is rejected with `ERR_INVALID_REFERENCE` (HTTP 422).

### 2.8. Monetary Precision and Rounding

All monetary amounts in this system are stored and exchanged as integer cents; there are no fractional-cent fields and no decimal money values in request or response bodies. Whenever a calculation produces a non-integer intermediate (the dues proration product and the tiered commission sum both can), the result is rounded to a whole number of cents using the round-half-up convention — a result whose fractional part is exactly one-half rounds away from zero. The specific point at which rounding is applied differs by calculation and is stated with each calculation in §3; in particular, dues proration rounds its single proration product once, and the fundraiser commission rounds once after all tier contributions have been summed.

### 2.9. The Fund Ledger and Conserved-Balance Accounting

All movement of money in the system is recorded as immutable `FundLedgerEntry` rows, and the council's reported balances are pure aggregations over those rows. Each entry names the `council_id` it belongs to, an optional `troop_id` (null for council-only accounts such as cash and liability), the `account` it posts to — one of `COUNCIL_CASH`, `PRODUCT_LIABILITY`, or `TROOP_DUES` — a signed `amount_cents` where a positive value is a credit and a negative value is a debit, a `source_kind` describing what originated the entry, and a `source_ref_id` pointing at the originating record. The `source_kind` is polymorphic and takes one of `PAYMENT` (dues flowing into `TROOP_DUES`), `FUNDRAISER_ORDER` (commission into `TROOP_DUES` at placement, plus cash and liability credits on fill), `RECHARTER` (the charter-fee sweep), or `REVERSAL` (a commission unwound when an order is cancelled or a fundraiser is closed). The `source_ref_id` carries the id of the originating `Payment`, `FundraiserOrder`, or `Troop`; it is a polymorphic pointer, not an enforced foreign key.

A council exposes two computed balances that are full re-aggregations on read. The `fund_cash_cents` is the sum of `amount_cents` over every entry for that council whose `account` is `COUNCIL_CASH`, and the `fund_liability_cents` is the sum of `amount_cents` over every entry whose `account` is `PRODUCT_LIABILITY`. These balances are well-defined because only a filled order ever credits cash and liability, and a filled order is terminal — the fundraiser-close path cancels only orders still in `PLACED`, never those already `FILLED` — so once posted those two credits are permanent. An order cancelled before it was filled never touched cash or liability at all; its only ledger footprint is the troop-dues commission, which its cancellation reverses. A council is created with both balances at zero.

### 2.10. The Logical Clock

All time-dependent evaluations — charter expiry, training expiry, event and booth interval comparisons — read a single server-managed logical clock rather than wall-clock time. On startup the clock reads exactly `2026-04-01T00:00:00Z`, and before any operator sets it the clock returns this default and never falls back to real time. A `CouncilRegistrar` may advance the clock by supplying a target instant as `to_iso8601`; afterward all deadline and expiry comparisons use the new value.

## 3. Business Logic & Workflows

### 3.1. Councils, Troops, and the Charter Lifecycle

A `CouncilRegistrar` stands up a council by supplying its `name`, the per-troop annual recharter base fee as `charter_fee_cents`, the annual youth and adult membership dues as `youth_dues_cents` and `adult_dues_cents`, and the active `program_year`. The fee and both dues amounts must be zero or greater, and the program year must be at least 2000. A council begins life with `fund_cash_cents` and `fund_liability_cents` both at zero, and those two balances thereafter are always recomputed from the ledger as described in §2.9.

Beneath a council, a registrar creates troops, each carrying a `unit_number` that must be unique within its council and a `program_type` of `CUB`, `SCOUTS`, or `VENTURING`. A duplicate unit number within the same council is rejected with `ERR_DUPLICATE_UNIT_NUMBER`. A new troop is stamped with its parent's `council_id`, opens in `charter_status` `PROVISIONAL`, computes its initial `recharter_posture` (which will be `BLOCKED` for a brand-new troop), and starts at `version` 1.

The charter lifecycle is a chain of registrar-driven transitions over `charter_status`. Rechartering takes a troop from `PROVISIONAL` to `CHARTERED`; it is also the path back from `LAPSED`, so a recharter is permitted only when `charter_status` is `PROVISIONAL` or `LAPSED`. A recharter is the most heavily guarded write in the system. It requires the troop's `recharter_posture` to be `READY` — if the posture is anything else the request is rejected with `ERR_RECHARTER_NOT_READY` — and it requires the supplied `expected_troop_version` to match the troop's current `version`, failing with `ERR_STALE_VERSION` otherwise. It further requires that the troop's settled dues balance be sufficient to cover the charter fee, as detailed in §3.7; a shortfall is rejected with `ERR_INSUFFICIENT_TROOP_FUNDS`. On success the charter moves to `CHARTERED`, the `charter_expires_at` is set to the end of the council's program year — the instant `December 31 23:59:59Z` of `program_year` — the charter-fee sweep posts its two ledger rows, the troop's `dues_account_cents` and the council's `fund_cash_cents` are recomputed, and the troop's `version` increments by one.

A chartered troop can later lapse, moving `charter_status` from `CHARTERED` to `LAPSED`; this is permitted only from `CHARTERED` and increments `version` by one. A lapsed troop can be dropped, moving from `LAPSED` to the terminal `DROPPED`; this is permitted only from `LAPSED` and likewise increments `version`. Any of these three transitions attempted from a state in which it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.2. Member Registration and the Dues-Driven Lifecycle

A member is added under a troop by either role, supplying the `member_type` (`YOUTH` or `ADULT`), the `full_name`, and the `birthdate` as an ISO date in `YYYY-MM-DD` form (used for youth age eligibility). A new member is stamped with the parent's `troop_id`, opens in `registration_status` `PENDING`, and — when a youth — begins at `rank` `SCOUT`. A member's `dues_paid_cents`, the cumulative total of their posted payments, is a computed field recomputed on read.

Registration is dues-driven and not a direct transition. To move from `PENDING` toward active status, the member must first have a dues invoice issued and then have it paid in full. When the cumulative posted payment amount against a member's `OPEN` invoice reaches or exceeds that invoice's amount, the system itself flips the invoice to `PAID`, advances the member's `registration_status` from `PENDING` to `REGISTERED`, and — because a youth's registration changes the troop's head count — recomputes the troop's `registered_youth_count` and `recharter_posture`.

A `TroopLeader` manages the rest of the member lifecycle. Suspending a member is permitted only while `registration_status` is `REGISTERED` and moves it to `SUSPENDED`, recomputing the youth count (when the member is a youth) and the posture. Reinstating is permitted only from `SUSPENDED` and returns the member to `REGISTERED`, again recomputing youth count and posture. Dropping a member is the terminal exit: from the `REGISTERED`, `SUSPENDED`, or `PENDING` states a drop moves the member to `DROPPED`, voids every `OPEN` `DuesInvoice` belonging to that member (each such invoice's `status` becomes `VOID`), and recomputes the troop's `registered_youth_count` when the member is a youth, its `cleared_leader_count` when the member is an adult, and its `recharter_posture`. A drop is also defined directly from `SUSPENDED` to `DROPPED`, which recomputes the posture. Any member transition attempted from a state where it is not defined is rejected with `ERR_INVALID_STATE`, and every member transition that changes a troop-derived field bumps the troop's `version`.

### 3.3. Issuing Dues Invoices and Posting Payments

Either role issues a dues invoice for a member by supplying the `issued_on` ISO date the invoice covers from, which serves as the proration anchor. The invoice records the member's `member_id` and the denormalized `troop_id`, computes its `amount_cents` from the proration rule below, and opens in `status` `OPEN`.

**Dues proration.** The base figure depends on the member: a youth member uses the council's `youth_dues_cents` and an adult member uses the council's `adult_dues_cents`. From the `issued_on` date the system determines the number of whole months remaining in the program year through December: this equals twelve minus one less than the month number of `issued_on`, which yields twelve for a January anchor and one for a December anchor, clamped to the range one through twelve. There is a full-dues floor of nine months: if the months remaining are at least nine, the full base amount is charged with no proration discount. Otherwise the invoice amount is the base multiplied by the months remaining and divided by twelve, with that single proration product rounded half-up to a whole number of cents. The result is always integer cents.

A payment is posted against an `OPEN` invoice by supplying the `invoice_id`, the `member_id`, and the `amount_cents`, which must be strictly greater than zero. Posting a payment creates a write-once record whose `status` is `POSTED` and immediately writes a `FundLedgerEntry` crediting the payment's `amount_cents` into `TROOP_DUES` with a `source_kind` of `PAYMENT`. A payment may not push the cumulative posted total for that invoice above the invoice's `amount_cents`; an overpayment is rejected with `ERR_OVERPAYMENT`. When the cumulative posted total reaches or exceeds the invoice amount, the invoice is settled to `PAID` and the member's registration advances as described in §3.2, with the owning troop recomputed.

### 3.4. Leader Credentials: Background Check and Training

Only an adult can become a leader. A `TroopLeader` opens a `LeaderCredential` against a member by supplying the `requested_by_user_id`, which records the opening operator's identity as the segregation-of-duties anchor. The credential may only be opened against a member whose `member_type` is `ADULT`; attempting it on a youth is rejected with `ERR_MEMBER_NOT_REGISTERED`. A new credential opens with `bgcheck_status` `NOT_STARTED`, `training_status` `UNTRAINED`, and `version` 1.

The credential carries two independent state dimensions on the same row. The background-check dimension is the lifecycle axis: a registrar starts the check, moving `bgcheck_status` from `NOT_STARTED` to `PENDING`. From `PENDING` the registrar resolves it by supplying an `outcome`; an `outcome` of `CLEAR` moves `bgcheck_status` to `CLEARED`, while an `outcome` of `FLAG` moves it to `FLAGGED`. Both resolutions are subject to segregation of duties: the resolving operator's `X-User-ID` must differ from the credential's `requested_by_user_id`, and a self-resolution is rejected with `ERR_SEGREGATION_OF_DUTIES`. Either resolution recomputes the owning troop's `cleared_leader_count` and `recharter_posture` — a clearance counts toward the leader tally only when training is also complete, and a flag removes the leader from the tally — and bumps the troop's `version`.

The training dimension evolves independently on the same credential. Completing training moves `training_status` from `UNTRAINED` to `TRAINED`, sets `training_expires_at` to the current logical-clock time plus the training validity window, and recomputes the troop's `cleared_leader_count` (a trained leader counts only when the background check is also cleared) and `recharter_posture`, bumping the troop's `version`. Any background-check or training transition attempted from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.5. Advancement: Requirement Sign-Off, the Revision Loop, and Approval

A `TroopLeader` opens an advancement for a member by supplying its `kind` (`RANK` or `BADGE`), its `target`, the `requirements_total` (which must be at least one), and — only when the kind is a merit badge — the `badge_code`; the `badge_code` is null for a rank advancement. For a rank advancement the `target` is one of `TENDERFOOT`, `SECOND_CLASS`, or `FIRST_CLASS`; for a badge advancement the `target` is the badge string carried in `badge_code`. The advancement opens in `status` `DRAFT` with `requirements_signed` at zero and `completion_pct` at zero.

Each requirement sign-off increases `requirements_signed` by one, capped so it never exceeds `requirements_total`, and recomputes `completion_pct` as the signed count divided by the total count, multiplied by one hundred, rounded half-up to two decimal places. Submitting the advancement for council review takes it from `DRAFT` to `SUBMITTED`, but only once every requirement is signed — that is, only when `requirements_signed` equals `requirements_total` (equivalently, `completion_pct` has reached one hundred). A premature submit is rejected with `ERR_REQUIREMENTS_INCOMPLETE`. On a successful submit the system stamps `submitted_by_user_id` with the acting operator's id.

Review is a cyclic loop. A registrar may return a submitted advancement, moving it from `SUBMITTED` to `RETURNED`. From `RETURNED` the leader may submit again — permitted only when `requirements_signed` still equals `requirements_total` — which moves it back to `SUBMITTED` and re-stamps `submitted_by_user_id` with the resubmitting operator's id. This `SUBMITTED → RETURNED → SUBMITTED` loop may repeat any number of times until the advancement is approved. Approving a submitted advancement moves it from `SUBMITTED` to the terminal `APPROVED`, but is gated by two conditions beyond the state itself: the approving operator's `X-User-ID` must differ from the advancement's `submitted_by_user_id` (a self-approval is rejected with `ERR_SEGREGATION_OF_DUTIES`), and the member must currently be `REGISTERED` (an approval against a non-registered member is rejected with `ERR_MEMBER_NOT_REGISTERED`). When an approved advancement is of kind `RANK`, the member's `rank` is advanced to the advancement's `target`; a badge approval leaves the rank untouched. Any advancement transition attempted from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.6. Events, Permission, Health Forms, and Confirmation

A `TroopLeader` creates an event under a troop by supplying the `title`, the `starts_at` and `ends_at` UTC instants, the `capacity` of confirmed registrations (at least one), and optionally `requires_health_form` (which defaults to true). The `ends_at` must be strictly after `starts_at`; otherwise the create is rejected with `ERR_INVALID_REQUEST`. The event records its `troop_id`, opens in `status` `OPEN` with `confirmed_count` at zero, and exposes `confirmed_count` as a recomputed count of its `CONFIRMED` registrations.

A registration is created against an event by supplying the `member_id`. It records the `event_id`, opens in `status` `HOLD`, and carries two parallel dimensions that begin unsatisfied: `permission_status` at `UNSIGNED` and `health_status` at `MISSING`. Signing the guardian permission form moves `permission_status` from `UNSIGNED` to `SIGNED`, and filing the health form moves `health_status` from `MISSING` to `ON_FILE`; both are permitted only while the registration is still on `HOLD` and neither changes the registration's overall `status`.

Confirming a registration is the gate that moves it from `HOLD` to `CONFIRMED`, and it requires every one of the following to hold: the registration is on `HOLD`, its `permission_status` is `SIGNED`, the event does not require a health form or else `health_status` is `ON_FILE`, the event's own `status` is `OPEN`, the event's `confirmed_count` is still below its `capacity`, and the member's `registration_status` is `REGISTERED`. A confirmation blocked specifically by an unsigned permission slip or a missing-but-required health form is rejected with `ERR_FORMS_INCOMPLETE`; a confirmation blocked because the event is already at capacity is rejected with `ERR_EVENT_FULL`. On success the registration becomes `CONFIRMED` and the event's `confirmed_count` increases by one.

A further temporal guard applies at confirmation: a member must never hold two confirmed registrations whose events' time windows collide. Treating each event's `[starts_at, ends_at]` window as a closed interval, two windows collide if they overlap or even merely touch at an endpoint — a zero gap is a collision, since the buffer is inclusive. A confirmation that would give the member a second overlapping-or-touching confirmed registration is rejected with `ERR_MEMBER_DOUBLE_BOOKED`.

A leader may cancel a registration. Cancelling a registration that is currently `CONFIRMED` moves it to the terminal `CANCELLED` and decreases the event's `confirmed_count` by one; cancelling one still on `HOLD` simply moves it to `CANCELLED` with no count change. Locking an event moves its `status` from `OPEN` to `LOCKED`, which freezes any further confirmations (no new `HOLD → CONFIRMED` transition is allowed once locked). Cancelling an event is permitted from either `OPEN` or `LOCKED` (and the cancel-from-`LOCKED` path is defined as well): it moves the event to the terminal `CANCELLED`, cascades every registration still in `HOLD` or `CONFIRMED` to `CANCELLED`, and recomputes the event's `confirmed_count` to zero. Event and registration transitions attempted from states where they are not defined are rejected with `ERR_INVALID_STATE`.

### 3.7. The Fundraiser: Inventory, Tiered Commission, and Order Fulfillment

A `CouncilRegistrar` creates a fundraiser under a council by supplying the `product` (`COOKIES` or `POPCORN`), the retail `unit_price_cents` (greater than zero), the supplier `unit_cost_cents` (zero or greater), and the `total_inventory_units` the council releases (zero or greater). The fundraiser records its `council_id`, opens in `status` `DRAFT`, starts with `allocated_units` at zero and `available_units` equal to `total_inventory_units`, and begins at `version` 1. The `available_units` is always the `total_inventory_units` minus `allocated_units`, where `allocated_units` is the sum of `units` across orders in `PLACED` or `FILLED` status. Taking the fundraiser live requires it to be in `DRAFT` and to have at least one unit of total inventory; it moves the `status` to `LIVE` and increments `version`. Only a `LIVE` fundraiser accepts orders.

A `TroopLeader` places an order against a live fundraiser by supplying the `fundraiser_id`, the selling `troop_id`, the `seller_member_id` credited with the sale, the `units` ordered (at least one), and the `expected_fundraiser_version` for the concurrency check. The order may not oversell inventory: if `units` exceeds the fundraiser's current `available_units`, the placement is rejected with `ERR_INSUFFICIENT_INVENTORY`. On a successful placement the order opens in `status` `PLACED`, records its `gross_cents` as `units` multiplied by the fundraiser's `unit_price_cents` at placement, computes its `troop_commission_cents` from the tiered schedule below, credits that commission into `TROOP_DUES`, increases the fundraiser's `allocated_units` by `units`, recomputes `available_units`, and increments the fundraiser's `version`.

**Tiered troop commission.** The commission is a marginal tiered rate applied to units, not to gross — each unit earns its own tier's rate against the unit price, and the tier boundaries are drawn over the cumulative units of this single order. The first 100 units (units one through one hundred) each earn fifteen percent of the unit price; units one hundred one through five hundred each earn twenty percent; and every unit beyond five hundred earns twenty-five percent. Concretely, the number of first-tier units is the smaller of the order's units and one hundred; the number of second-tier units is the order's units minus one hundred, floored at zero, but no more than four hundred (the span between the first and second boundaries); and the number of third-tier units is whatever remains above five hundred, floored at zero. Each tier's unit count is multiplied by the unit price and by its rate, the three tier contributions are summed, and that single sum is rounded half-up to whole cents exactly once after summing.

Filling an order, permitted only while the order is `PLACED` and the fundraiser is still `LIVE`, moves the order to `FILLED` and posts the cash side of the sale: a `FundLedgerEntry` credits the order's `gross_cents` into `COUNCIL_CASH` and another credits `units` multiplied by the fundraiser's `unit_cost_cents` into `PRODUCT_LIABILITY`, both with a `source_kind` of `FUNDRAISER_ORDER`; the troop's `dues_account_cents` continues to reflect the commission already credited at placement. Cancelling a placed order moves it to the terminal `CANCELLED`, decreases the fundraiser's `allocated_units` by that order's `units` and recomputes `available_units`, reverses the order's `troop_commission_cents` out of `TROOP_DUES` via a reversal ledger entry, and recomputes the troop's `dues_account_cents`. Closing a fundraiser is permitted only from `LIVE`; it moves the `status` to `CLOSED`, auto-cancels every order still in `PLACED` (filled orders are never touched), and for each auto-cancelled order recomputes `allocated_units` and `available_units` and reverses its `troop_commission_cents` from `TROOP_DUES` with a reversal entry. Any fundraiser or order transition attempted from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

**Recharter balance sweep and settled-versus-projected funds.** The recharter fee sweep distinguishes two views of a troop's dues. The projected view, used for posture preview, counts the commissions from both `PLACED` and `FILLED` orders along with posted payments. The settled view, which is the one the recharter eligibility gate uses, counts only the commissions from `FILLED` orders together with posted payments. The recharter gate requires the troop's settled `TROOP_DUES` total to be at least the council's `charter_fee_cents`; if the settled funds fall short, the recharter is rejected with `ERR_INSUFFICIENT_TROOP_FUNDS`. When the gate passes, the sweep posts two ledger rows under `source_kind` `RECHARTER`: it debits `charter_fee_cents` from `TROOP_DUES` (a negative `amount_cents`) and credits the same `charter_fee_cents` into `COUNCIL_CASH` (a positive `amount_cents`). The charter fee thus leaves the troop's dues account and enters council cash with the system's net cash unchanged — a conserved quantity — and the troop's `dues_account_cents` and the council's `fund_cash_cents` are both recomputed.

### 3.8. Booth Reservations

A `TroopLeader` reserves a booth slot against a fundraiser by supplying the reserving `troop_id`, the `location_code` identifying the booth location, and the slot's `starts_at` and `ends_at` UTC instants, where `ends_at` must be strictly after `starts_at`. A reservation records its `fundraiser_id`, opens in `status` `BOOKED`, and can later be released, moving its `status` from `BOOKED` to `RELEASED` and freeing the slot.

Booth overlap is scoped per `location_code`: within a single location, a new booked slot's half-open `[starts_at, ends_at)` interval must not overlap that of any other still-`BOOKED` reservation at the same `location_code`. Because the interval is half-open, two slots that merely touch end-to-end (a zero gap, where one ends exactly when the next begins) are allowed and do not conflict, in contrast to the closed, touch-rejecting rule used for a member's confirmed events. A reservation whose interval overlaps an existing booked slot at the same location is rejected with `ERR_BOOTH_CONFLICT`.

### 3.9. Validation Ordering and Council Reporting

When several checks could fire on a single request, they are evaluated in a fixed priority order so that the earliest applicable failure is the one reported. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every path-referenced resource validated left to right (`ERR_NOT_FOUND`), then body-level referential integrity for the create endpoints that carry foreign keys (`ERR_INVALID_REFERENCE`), then the state-machine precondition that the target be in a state from which the transition is defined (`ERR_INVALID_STATE`), then the optimistic-concurrency version check on recharter and order placement (`ERR_STALE_VERSION`). After those come the business-safety checks: segregation of duties on background-check resolution and advancement approval (`ERR_SEGREGATION_OF_DUTIES`), then the member-registration and adult-only credential guard (`ERR_MEMBER_NOT_REGISTERED`). Thereafter the remaining business constraints apply in order — advancement completeness (`ERR_REQUIREMENTS_INCOMPLETE`), event-registration form completeness (`ERR_FORMS_INCOMPLETE`), booth conflict (`ERR_BOOTH_CONFLICT`), member double-booking (`ERR_MEMBER_DOUBLE_BOOKED`), event capacity (`ERR_EVENT_FULL`), and order inventory sufficiency (`ERR_INSUFFICIENT_INVENTORY`) — followed by the fiscal recharter-funds gate (`ERR_INSUFFICIENT_TROOP_FUNDS`) and the recharter-posture gate (`ERR_RECHARTER_NOT_READY`). General body well-formedness — required fields present and well-typed, valid enums, `ends_at` after `starts_at`, `units` at least one, `amount_cents` greater than zero, and unique troop unit number within the council — is reported as `ERR_INVALID_REQUEST`, and the no-overpayment fiscal check on payments as `ERR_OVERPAYMENT`. The practical consequence is that, for example, a recharter that is both behind on funds and not posture-ready surfaces its funds shortfall before its posture shortfall, and any request failing authentication never reaches a business check at all.

A `CouncilRegistrar` reads the council ledger to review every `FundLedgerEntry` for a council, optionally narrowing by `account` or by `troop_id`, and reads the council report — a reporting summary of troop roster counts, charter postures, and fund balances — with all derived counts and balances recomputed at read time. A troop-scoped ledger read is available to both roles and returns the `FundLedgerEntry` rows routed to that troop, optionally narrowed by `account`. List endpoints across the system accept their natural filters — troops by `council_id`; members by `troop_id` and `member_type`; dues invoices by `member_id`, `troop_id`, or `status`; payments by `invoice_id` or `member_id`; leader credentials by `member_id`; advancements by `member_id` or `status`; events by `troop_id` or `status`; registrations by `event_id` or `member_id`; fundraisers by `council_id` or `status`; orders by `fundraiser_id`, `troop_id`, or `seller_member_id`; and booth reservations by `fundraiser_id`, `troop_id`, or `location_code`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including all state-transition operations and the recharter, lapse, and drop actions — return a `200 OK` status code, as do all read operations and the clock-set capability.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/councils` | Create a Council | CouncilRegistrar |
| GET | `/councils/{id}` | Get a Council with recomputed fund balances | CouncilRegistrar, TroopLeader |
| GET | `/councils/{id}/ledger` | List fund ledger entries for a council | CouncilRegistrar |
| GET | `/councils/{id}/report` | Council reporting summary | CouncilRegistrar |
| POST | `/councils/{id}/troops` | Create a Troop under a Council | CouncilRegistrar |
| GET | `/troops/{id}` | Get a Troop with recomputed counts and posture | CouncilRegistrar, TroopLeader |
| GET | `/troops` | List troops; filter by council_id | CouncilRegistrar, TroopLeader |
| GET | `/troops/{id}/ledger` | List fund ledger entries scoped to a troop | CouncilRegistrar, TroopLeader |
| POST | `/troops/{id}/recharter` | Recharter a troop (OCC-guarded; sweeps charter fee) | CouncilRegistrar |
| POST | `/troops/{id}/lapse` | Lapse a chartered troop | CouncilRegistrar |
| POST | `/troops/{id}/drop` | Drop a lapsed troop | CouncilRegistrar |
| POST | `/troops/{id}/members` | Register a Member under a Troop | CouncilRegistrar, TroopLeader |
| GET | `/members/{id}` | Get a Member | CouncilRegistrar, TroopLeader |
| GET | `/members` | List members; filter by troop_id | CouncilRegistrar, TroopLeader |
| POST | `/members/{id}/suspend` | Suspend a registered member | TroopLeader |
| POST | `/members/{id}/reinstate` | Reinstate a suspended member | TroopLeader |
| POST | `/members/{id}/drop` | Drop a member; voids open invoices | TroopLeader |
| POST | `/members/{id}/dues-invoices` | Issue a prorated dues invoice | CouncilRegistrar, TroopLeader |
| GET | `/dues-invoices/{id}` | Get a DuesInvoice | CouncilRegistrar, TroopLeader |
| GET | `/dues-invoices` | List dues invoices | CouncilRegistrar, TroopLeader |
| POST | `/payments` | Post a Payment against an open invoice | CouncilRegistrar, TroopLeader |
| GET | `/payments/{id}` | Get a Payment | CouncilRegistrar, TroopLeader |
| GET | `/payments` | List payments | CouncilRegistrar, TroopLeader |
| POST | `/members/{id}/leader-credentials` | Open a leader credential for an adult member | TroopLeader |
| GET | `/leader-credentials/{id}` | Get a LeaderCredential | CouncilRegistrar, TroopLeader |
| GET | `/leader-credentials` | List leader credentials | CouncilRegistrar, TroopLeader |
| POST | `/leader-credentials/{id}/start-bgcheck` | Start the background check | CouncilRegistrar |
| POST | `/leader-credentials/{id}/resolve-bgcheck` | Resolve background check (segregation of duties) | CouncilRegistrar |
| POST | `/leader-credentials/{id}/complete-training` | Mark youth-protection training complete | CouncilRegistrar |
| POST | `/members/{id}/advancements` | Create an Advancement for a member | TroopLeader |
| GET | `/advancements/{id}` | Get an Advancement | CouncilRegistrar, TroopLeader |
| GET | `/advancements` | List advancements | CouncilRegistrar, TroopLeader |
| POST | `/advancements/{id}/sign-requirement` | Sign off one requirement | TroopLeader |
| POST | `/advancements/{id}/submit` | Submit advancement for review | TroopLeader |
| POST | `/advancements/{id}/return` | Return a submitted advancement for revision | CouncilRegistrar |
| POST | `/advancements/{id}/approve` | Approve a submitted advancement (segregation of duties) | CouncilRegistrar |
| POST | `/troops/{id}/events` | Create an Event under a troop | TroopLeader |
| GET | `/events/{id}` | Get an Event | CouncilRegistrar, TroopLeader |
| GET | `/events` | List events; filter by troop_id | CouncilRegistrar, TroopLeader |
| POST | `/events/{id}/lock` | Lock an event | TroopLeader |
| POST | `/events/{id}/cancel` | Cancel an event; cascades to registrations | TroopLeader |
| POST | `/events/{id}/registrations` | Create an EventRegistration | TroopLeader |
| GET | `/event-registrations/{id}` | Get an EventRegistration | CouncilRegistrar, TroopLeader |
| GET | `/event-registrations` | List registrations | CouncilRegistrar, TroopLeader |
| POST | `/event-registrations/{id}/sign-permission` | Sign the guardian permission form | TroopLeader |
| POST | `/event-registrations/{id}/file-health` | File the health form | TroopLeader |
| POST | `/event-registrations/{id}/confirm` | Confirm a registration | TroopLeader |
| POST | `/event-registrations/{id}/cancel` | Cancel a registration | TroopLeader |
| POST | `/councils/{id}/fundraisers` | Create a Fundraiser under a council | CouncilRegistrar |
| GET | `/fundraisers/{id}` | Get a Fundraiser with recomputed inventory | CouncilRegistrar, TroopLeader |
| GET | `/fundraisers` | List fundraisers; filter by council_id | CouncilRegistrar, TroopLeader |
| POST | `/fundraisers/{id}/go-live` | Open a fundraiser for orders | CouncilRegistrar |
| POST | `/fundraisers/{id}/close` | Close a fundraiser; cancels placed orders | CouncilRegistrar |
| POST | `/fundraiser-orders` | Place a FundraiserOrder (OCC-guarded) | TroopLeader |
| GET | `/fundraiser-orders/{id}` | Get a FundraiserOrder | CouncilRegistrar, TroopLeader |
| GET | `/fundraiser-orders` | List orders | CouncilRegistrar, TroopLeader |
| POST | `/fundraiser-orders/{id}/fill` | Fill an order; posts cash and liability | TroopLeader |
| POST | `/fundraiser-orders/{id}/cancel` | Cancel a placed order; reverses commission | TroopLeader |
| POST | `/fundraisers/{id}/booth-reservations` | Reserve a booth slot | TroopLeader |
| GET | `/booth-reservations/{id}` | Get a BoothReservation | CouncilRegistrar, TroopLeader |
| GET | `/booth-reservations` | List booth reservations | CouncilRegistrar, TroopLeader |
| POST | `/booth-reservations/{id}/release` | Release a booth slot | TroopLeader |
| POST | `/_clock/set_current_utc` | Set the server logical clock | CouncilRegistrar |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REFERENCE` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_MEMBER_NOT_REGISTERED` | 409 Conflict |
| `ERR_REQUIREMENTS_INCOMPLETE` | 409 Conflict |
| `ERR_FORMS_INCOMPLETE` | 409 Conflict |
| `ERR_BOOTH_CONFLICT` | 409 Conflict |
| `ERR_MEMBER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_EVENT_FULL` | 409 Conflict |
| `ERR_INSUFFICIENT_INVENTORY` | 409 Conflict |
| `ERR_INSUFFICIENT_TROOP_FUNDS` | 409 Conflict |
| `ERR_RECHARTER_NOT_READY` | 409 Conflict |
| `ERR_OVERPAYMENT` | 409 Conflict |
| `ERR_DUPLICATE_UNIT_NUMBER` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
