# Roommate Expense Split API — Product Requirements Document

## 1. Introduction

Finding a compatible roommate and then keeping the money straight afterward are two problems that households usually solve with a patchwork of spreadsheets, group chats, and trust. This API unifies both halves into a single coherent platform: it helps a prospective roommate discover a room, scores how well an applicant fits a lister's preferences, and — once people actually move in — keeps a running, conserved ledger of who owes whom for rent, utilities, and the everyday shared expenses of cohabitation.

The product is built around a shared household ledger whose central guarantee is conservation: at any moment, the sum of every member's net position is exactly zero, because every dollar one roommate is owed is a dollar another roommate owes. From this single invariant flow the system's hardest behaviors — prorating rent when someone leaves mid-month, redistributing the freed share across the people who remain, freezing the books while a neutral mediator adjudicates a disputed charge, and rejecting a settle-up payment that races ahead of a ledger the payer has not actually observed. The sections below describe the access model and system-wide contracts first, then walk through the full lifecycle from listing a room to dissolving a household.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint regardless of the specific workflow being exercised.

### 2.1. User and Role-Based Access Control

Every request, with the narrow exceptions noted below, must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. The system recognizes exactly three roles, spelled precisely as `Roommate`, `DisputeMediator`, and `PlatformOperator`. If either header is missing, or if `X-User-Role` does not name a known role, the request is rejected with `ERR_UNAUTHENTICATED`. Two endpoints are deliberately exempt from authentication: registering a new roommate profile and setting the server clock — these may be called without valid headers. When an authenticated caller holds a role that is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`. When the caller holds the correct role but is not the specific owner, manager, or party that the operation requires, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

The three roles map to identity in two different ways. When `X-User-Role` is `Roommate`, `X-User-ID` is the `id` of the acting `RoommateProfile`; every ownership check on a resource that references a profile — a listing's `lister_id`, a membership's `profile_id`, a settlement's `from_profile_id` or `to_profile_id`, a dispute's `filed_by_id`, and the manager of a household — compares the relevant foreign-key field on that resource to `X-User-ID`. A `Roommate` lists rooms, applies to listings, manages a household they lister, records bill payments, logs and voids expenses, proposes and confirms settle-ups, schedules and acknowledges reminders, and files disputes. When `X-User-Role` is `DisputeMediator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any profile `id`, though it does use it to enforce that the mediator acting on a dispute is not the same person who filed it. A `DisputeMediator` claims, resolves, rejects, and reopens disputes, but may never file or adjudicate disputes interchangeably with the parties involved. When `X-User-Role` is `PlatformOperator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the operator advances the server clock and runs the reminder-dispatch batch. All three roles may perform any read (GET) operation on any resource.

A further segregation-of-duties rule binds the mediator role: the `DisputeMediator` acting to claim, resolve, or reject a dispute must not be the dispute's `filed_by_id`. A violation is rejected with `ERR_SELF_ADJUDICATION`. This check is evaluated as an authorization concern, ahead of any state or business validation on the dispute itself.

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

### 2.4. Common Resource Properties and Identifiers

Most top-level resources — `RoommateProfile`, `RoomListing`, `MatchRequest`, `Household`, `Membership`, `Bill`, `Expense`, `Settlement`, `PaymentReminder`, and `Dispute` — carry a standard set of system-managed fields. Each has an `id`, a unique server-minted UUID with no type prefix. Each has a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recording when the resource was first created. Each has an `updated_at` timestamp of the same format, refreshed on every mutation, and a `version`, an integer that starts at its initial value and increments by one with every modification to the resource.

Two resources are deliberate exceptions because they exist only as immutable child rows of their parents. A `BillSplit` (a single member's share of one bill) and an `ExpenseShare` (a single participant's portion of one expense) carry only an `id` and a `created_at`; they have no `updated_at` and no `version`. When the parent recomputes shares, it replaces these rows rather than versioning them in place.

### 2.5. Nested Resource Retrieval and Referential Existence

Several read endpoints expose a resource's children or back-references — a household's memberships, bills, expenses, settlements, and disputes; a bill's splits; an expense's shares; and, for a given profile, the bill-splits and expense-shares it owes across the system. For any request whose path or body names one or more resource identifiers, existence is validated left-to-right: the first identifier in the path that does not resolve to an existing resource causes the request to be rejected immediately with `ERR_NOT_FOUND`, before any deeper lookup or business rule is attempted. The same `ERR_NOT_FOUND` governs every foreign-key field carried in a request body — a `household_id`, `listing_id`, `applicant_id`, `bill_id`, `settlement_id`, `expense_id`, `payer_id`, `from_profile_id`, `to_profile_id`, `filed_by_id`, or any `participant_ids` entry that names a resource the server has never seen.

### 2.6. The Conservation Invariant and the Net-Balance Ledger

Every household maintains a single conserved ledger. Each member of a household carries a `net_balance_cents` figure scoped to the household they currently belong to: a positive value means the household owes that member (they are a creditor, typically because they paid for something shared), while a negative value means the member owes the household (they are a debtor). A profile that belongs to no household has a `net_balance_cents` of zero. Whenever the ledger is recomputed, a member's net position is built from four streams measured in whole cents: the total of all amounts they paid up front on `POSTED` expenses (their credits), minus the total of the expense shares assigned to them across `POSTED` expenses and any unpaid bill shares they still owe (their obligations), plus the total of confirmed settlement amounts they have paid as a debtor, minus the total of confirmed settlement amounts they have received as a creditor. No rounding occurs here because every input is already an integer number of cents.

The household exposes `active_member_count`, the number of memberships currently in `ACTIVE` status, and `ledger_sum_cents`, a conservation field equal to the sum of `net_balance_cents` across every `ACTIVE` and `MOVED_OUT` member. After every ledger-mutating operation — logging or voting an expense, confirming a settlement, resolving a dispute that adjusts an expense, or moving a member out — `ledger_sum_cents` must come back to exactly zero. This zero-sum guarantee is the system's core integrity check; any operation that would leave it non-zero is a defect, not a permitted state.

### 2.7. Whole-Cent Money and Remainder Distribution

All monetary amounts are stored and computed as whole integer cents; the API never represents money as a fractional or floating-point value. When a total must be divided across several people and does not divide evenly, the system uses a deterministic floor-then-distribute rule rather than ad-hoc rounding. Each participant's exact weighted portion is first floored to whole cents. The cents left over after flooring — always a non-negative number strictly smaller than the participant count — are then handed out one cent at a time, to participants taken in ascending order of their share row's `created_at`, until the remainder is exhausted. The result is that the individual shares always sum back to the original total exactly. Where a calculation prorates an amount by occupied days, that single prorated figure is rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway is rounded up).

### 2.8. Hierarchical State Propagation and Cascades

Many operations mutate more than one resource. The system performs these cascades automatically and synchronously: the caller acts on one resource, and the server propagates the consequences to its parents, children, and ledger without requiring separate requests. Activating a membership, for instance, may flip a household from `FORMING` to `ACTIVE` and close the underlying listing; moving a member out re-prorates a rent bill, redistributes shares, recomputes every net balance, and may dissolve the household entirely. Each resource that is mutated as part of a cascade has its own `updated_at` refreshed and its own `version` incremented, exactly as if it had been the direct target. The specific cascades are described in the workflow narratives of Section 3, where each origin operation is paired with the full chain of effects it triggers.

### 2.9. Ledger Freeze During Adjudication

A household has a `status` of `FORMING`, `ACTIVE`, `FROZEN`, or `DISSOLVED`. While a dispute is being actively reviewed, the household is held in `FROZEN`, and the ledger is sealed: any ledger-mutating write attempted against a frozen household is rejected with `ERR_HOUSEHOLD_FROZEN`. Four operations are gated by this freeze — logging a new expense, confirming a settlement, recording a bill payment, and moving a member out. All four return `ERR_HOUSEHOLD_FROZEN` while the household is `FROZEN`. The freeze is released automatically when adjudication ends, as described in Section 3.

### 2.10. Optimistic Concurrency on Settlement Confirmation

Confirming a settlement is the one ledger write protected by optimistic concurrency control, because a confirm rewrites both the debtor's and the creditor's `net_balance_cents` and advances the household's `version`. A request to confirm a settlement must carry `expected_household_version`, the household `version` the client last observed. If that value does not equal the household's current `version` — because some other ledger write advanced the household since the client read it — the confirm is rejected with `ERR_STALE_HOUSEHOLD_VERSION` and HTTP status 412, so the client can never reduce a ledger position it has not actually seen. No other endpoint accepts or requires a version field; only settlement confirmation participates in this check.

### 2.11. Validation Ordering

When several checks apply to a single operation, they are evaluated in a fixed priority so that the error a client sees is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role permission (`ERR_FORBIDDEN_ROLE`), then resource ownership (`ERR_NOT_RESOURCE_OWNER`), then — for dispute adjudication — segregation of duties (`ERR_SELF_ADJUDICATION`). Existence of every referenced resource (`ERR_NOT_FOUND`) is checked next, then whether the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`), then the frozen-household gate (`ERR_HOUSEHOLD_FROZEN`). Only after all of those pass does the system evaluate the operation-specific business rules described in Section 3. Within settlement confirmation specifically, the household-member, fiscal, and stale-version checks follow this same after-the-gates ordering; the precise sequence among them is called out in the settlement workflow. Independently of this ordering, any request that omits a required field or supplies a field that violates its declared type or range constraint — a negative `monthly_income_cents`, a `cleanliness` outside 1 through 5, a non-positive `total_amount_cents`, and the like — is rejected with `ERR_VALIDATION`.

## 3. Business Logic & Workflows

### 3.1. Profiles, Listings, and Establishing Compatibility

Everything begins with a `RoommateProfile`. Registering one is open to anyone and takes an `email`, a `full_name`, a declared `monthly_income_cents`, a self-rated `cleanliness` on a scale where the value is an integer from 1 to 5 inclusive (5 being the tidiest), a `sleep_schedule` that is one of `EARLY_BIRD`, `NIGHT_OWL`, or `FLEXIBLE`, and two lifestyle booleans, `smoker` and `pets`, each of which defaults to false when omitted. Declared income must be zero or greater. A freshly registered profile starts with a `net_balance_cents` of zero. Email is the login and contact handle and must be non-empty and unique across all profiles; registering a second profile with an email already in use is rejected with `ERR_EMAIL_TAKEN`.

A roommate who has a room to offer creates a `RoomListing`. The listing names its `lister_id` (the offering profile), a non-empty `title`, a `monthly_rent_cents` that must be strictly greater than zero, a `capacity` that is an integer from 1 to 8 inclusive giving the maximum number of co-resident active memberships the room admits at any single instant, a `room_size_sqft` that must be strictly greater than zero, and the lister's preferences: a desired minimum `wants_cleanliness` from 1 to 5 inclusive, a `wants_sleep_schedule` of `EARLY_BIRD`, `NIGHT_OWL`, or `FLEXIBLE`, and two dealbreaker flags, `no_smokers` and `no_pets`, each defaulting to false. The listing also fixes a `split_policy` of `EQUAL`, `BY_ROOM_SIZE`, or `BY_INCOME` (defaulting to `EQUAL`), which will later be snapshotted onto the household. A listing is born with a `status` of `OPEN` and closes to `CLOSED` once its household fills to capacity.

An applicant pursues a room by submitting a `MatchRequest` naming the `listing_id` and the `applicant_id`, optionally choosing a `scoring_mode` of `STRICT` or `LENIENT` (defaulting to `STRICT`). The applicant may not be the lister of the same listing; a self-application is rejected with `ERR_SELF_APPLICATION`. At creation the system computes and freezes a `compatibility_score`, an integer from 0 to 100 reflecting how well the applicant fits the listing. The score blends three weighted factors. The first is a cleanliness fit: take the absolute difference between the applicant's `cleanliness` and the listing's `wants_cleanliness`, subtract it from 5, take whichever is larger of that and 0, then divide by 5 — yielding a fraction from 0 to 1. The second is a sleep fit worth either 1 or 0: it is 1 when either side's schedule is `FLEXIBLE`, or when the applicant's `sleep_schedule` exactly equals the listing's `wants_sleep_schedule`; otherwise it is 0. The third is a lifestyle fit that begins at 1.0 and loses 0.5 if the listing sets `no_smokers` and the applicant is a `smoker`, and loses another 0.5 if the listing sets `no_pets` and the applicant has `pets`, with the result floored at 0. The base score is the cleanliness fit multiplied by 40, plus the sleep fit multiplied by 30, plus the lifestyle fit multiplied by 30, giving a value on a 0-to-100 range, which is then rounded half-up to a whole integer.

The two `scoring_mode` variants differ only in how dealbreakers land. Under `STRICT`, if either dealbreaker is actually violated — that is, the listing forbids smokers and the applicant smokes, or the listing forbids pets and the applicant keeps pets — the score is forced to exactly 0 regardless of the other factors. Under `LENIENT`, no hard-zeroing occurs: the dealbreakers only subtract their 0.5 each from the lifestyle fit, and the rounded weighted value stands as the score. When a withdrawn request is later re-applied, the `compatibility_score` is recomputed the same way against the listing's then-current preferences.

### 3.2. The Match Request Lifecycle

A `MatchRequest` opens in `PENDING` and can travel to `ACCEPTED`, `REJECTED`, or `WITHDRAWN`; of these, `ACCEPTED` and `REJECTED` are terminal, while `WITHDRAWN` is a way-station that can cycle back. Each action is gated by who may take it and the request's current state; an action requested from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

Acceptance is the lister's prerogative. The acting roommate must be the lister of the request's listing, the listing must be `OPEN`, and the listing's household (if one already exists) must have an `active_member_count` strictly below the listing's `capacity`. The applicant's frozen `compatibility_score` must also reach the platform's match threshold of 60; a request whose score is below 60 cannot be accepted and is rejected with `ERR_BELOW_MATCH_THRESHOLD`. When acceptance succeeds, the request moves from `PENDING` to `ACCEPTED`. If no household yet exists for the listing, one is created in `FORMING` status with its `manager_id` set to the lister, its `listing_id` set to the listing, and its `split_policy` copied from the listing's `split_policy`. A `Membership` is then created for the `applicant_id` in `PENDING` status, opening the household-formation path; the applicant does not become active merely by being accepted.

Rejection is also the lister's prerogative and simply moves the request from `PENDING` to `REJECTED`. Withdrawal belongs to the applicant: the acting roommate must be the request's `applicant_id`, and withdrawal moves a `PENDING` request to `WITHDRAWN`. A withdrawn request can be revived by the same applicant through a re-apply, provided the listing is still `OPEN`; re-applying carries the request from `WITHDRAWN` back to `PENDING` and recomputes the `compatibility_score` against the listing's current preferences.

### 3.3. Activating Memberships and Forming the Household

A `Membership` records that a profile has joined a household. It carries the `household_id`, the `profile_id`, a planned `move_in_date`, a `planned_move_out_date` used by the forward-looking proration estimate, and an `actual_move_out_date` that is null until the member actually leaves. It also exposes two computed day-counts, `occupied_days_estimate` and `occupied_days_actual`, both starting at zero, and a `status` of `PENDING`, `ACTIVE`, or `MOVED_OUT`, where `PENDING` is the entry state and `MOVED_OUT` is terminal.

Activation is performed by the household's manager. The acting roommate must be the `manager_id` of the membership's household, and the household must be in `FORMING` or `ACTIVE` status. Two capacity gates then apply, and their order matters. First, for a single-occupancy room — one whose listing `capacity` equals 1 — the activating membership's half-open occupancy interval, running from its `move_in_date` up to but not including its `planned_move_out_date`, must not overlap that of any existing `ACTIVE` membership on the same room. Two such intervals overlap precisely when the new member's `move_in_date` falls strictly before the other member's `planned_move_out_date` and the other member's `move_in_date` falls strictly before the new member's `planned_move_out_date`; intervals that merely touch at an endpoint do not overlap. A violation is rejected with `ERR_OCCUPANCY_OVERLAP`, and this temporal check is evaluated before the capacity-count gate. Second, the household's `active_member_count` must be strictly below the listing's `capacity`; an activation that would push the count to or past capacity is rejected with `ERR_ROOM_AT_CAPACITY`.

When activation succeeds, the membership moves from `PENDING` to `ACTIVE` and the cascade runs. The household's `active_member_count` is recomputed from its `ACTIVE` memberships. If the household was `FORMING`, it advances to `ACTIVE`. If the recomputed count reaches the listing's `capacity`, the listing's `status` flips to `CLOSED`. Finally, the new member's `occupied_days_estimate` is refreshed using the forward-looking proration variant against the household's current-period rent bill if one exists; when no current-period rent bill exists yet, `occupied_days_estimate` remains zero.

### 3.4. Bills, Splitting, and Payment

A roommate issues a `Bill` against a household by supplying the `household_id`, a `bill_type` of either `RENT` or `UTILITIES`, a `total_amount_cents` strictly greater than zero, a `period_start`, and a `period_end`. The billing period is a closed interval inclusive of both endpoints, and `period_end` must be strictly after `period_start`; a period that fails this is rejected with `ERR_INVALID_PERIOD`. Two rent bills for the same household may never cover overlapping periods: a new `RENT` bill whose closed `[period_start, period_end]` interval overlaps that of any existing `RENT` bill of the household is rejected with `ERR_BILL_PERIOD_OVERLAP`. At issue time the bill snapshots the household's split policy into `split_policy_used`, and the total is divided across the household's `ACTIVE` members into `BillSplit` rows. The bill carries two independent status dimensions: a `payment_status` of `UNPAID`, `PARTIALLY_PAID`, or `PAID`, and a `reminder_status` of `NONE`, `SCHEDULED`, or `SENT`. The two advance independently of each other.

The split itself distributes `total_amount_cents` across the participating `ACTIVE` members, taken in ascending order of their membership `created_at`. Each member receives a weight determined by `split_policy_used`: under `EQUAL` every member's weight is 1; under `BY_ROOM_SIZE` every member's weight is the listing's `room_size_sqft` (so a single room makes this behave like `EQUAL`); and under `BY_INCOME` a member's weight is the larger of 1 and their `monthly_income_cents`. With the total weight summed across members, each member's base share is the bill total multiplied by that member's weight, divided by the total weight, then floored to whole cents. The cents left over — the bill total minus the sum of the floored bases, always at least zero and strictly less than the member count — are distributed one cent per member, members taken in ascending `created_at` order, until exhausted. Each member's `share_cents` is the result, and the shares always sum back to `total_amount_cents` exactly. Every `BillSplit` row records the `bill_id` it belongs to, the `profile_id` who owes it, the computed `share_cents`, and a `paid` flag that starts false.

Recording a payment is how a member settles their own split. A roommate who is an `ACTIVE` member of the bill's household records a payment by naming the `profile_id` whose share is being paid; the household must not be `FROZEN`, and that member's `BillSplit.paid` must still be false. The payment flips that member's `paid` to true. If, after the flip, some but not all of the bill's splits are paid, the bill advances from `UNPAID` to `PARTIALLY_PAID`. If the flip makes every split paid, the bill advances to `PAID` — either from `PARTIALLY_PAID`, or directly from `UNPAID` in the single-split case where one payment settles the whole bill. When a bill reaches `PAID`, any `SCHEDULED` payment reminder still outstanding for that bill is moved to `CANCELLED`.

### 3.5. Move-Out, Proration, and the Redistribution Cascade

Moving out is the system's deepest cascade. Either the member themselves (the membership's `profile_id`) or the household's manager may move a member out, and the household must not be `FROZEN`. The member's `actual_move_out_date` is set to the server's current clock instant, and the membership advances from `ACTIVE` to `MOVED_OUT`.

Proration then settles the departing member's rent fairly. The relevant bill is the household's current-period unpaid `RENT` bill — the one whose `[period_start, period_end]` interval contains the `actual_move_out_date`. The period length in days is the count of calendar days from `period_start` through `period_end` inclusive of both endpoints, i.e. the difference between the two dates plus one. The member's realized occupancy, `occupied_days_actual`, counts the inclusive days from the later of their `move_in_date` and the period start through the earlier of their `actual_move_out_date` and the period end — again counting both endpoints, and clamped to zero if the resulting end precedes the start. The forward-looking estimate variant, `occupied_days_estimate`, is computed the same way but using `planned_move_out_date` in place of the actual date; it is the figure refreshed at activation and at rent-bill issue, and it can diverge from the actual count when a member leaves earlier or later than planned.

With days in hand, the departing member's rent share is reset to a prorated figure: their original full share multiplied by `occupied_days_actual`, divided by the period day-count, rounded half-up to whole cents. The difference between their original full share and this prorated amount is the freed remainder, and it is redistributed across the members who remain `ACTIVE` using the same weighted floor-then-remainder rule described for bill splitting, with the leftover cents handed out in ascending membership `created_at` order. Throughout, the bill's `total_amount_cents` continues to equal the sum of all `share_cents`. Once the splits are settled, every member's `net_balance_cents` is recomputed and the household's `ledger_sum_cents` is confirmed to remain zero. The household's `active_member_count` is decremented; if it reaches zero, the household transitions to the terminal `DISSOLVED` state. Finally, if the listing was `CLOSED` and the household is now below capacity, the listing reopens to `OPEN`.

### 3.6. Shared Expenses and the Net-Balance Effect

Beyond formal bills, roommates log day-to-day shared costs as an `Expense`. Logging one requires the household not be `FROZEN` and takes the `household_id`, the `payer_id` of the member who fronted the money, a non-empty `description`, a `total_amount_cents` strictly greater than zero, a `split_mode` of `EQUAL` or `CUSTOM` (defaulting to `EQUAL`), a non-empty list of `participant_ids` sharing the cost, and — only under `CUSTOM` — a `share_overrides` map. The payer and every participant named in `participant_ids` must each be an `ACTIVE` member of the named household; if any is not, the request is rejected with `ERR_NOT_HOUSEHOLD_MEMBER`. Under `EQUAL`, the total is divided across the participants using the same whole-cent floor-then-remainder distribution, producing one `ExpenseShare` per participant. Under `CUSTOM`, the `share_overrides` map assigns explicit cents per profile; its keys must be exactly the `participant_ids` and its values must sum to `total_amount_cents`, or the request is rejected with `ERR_SHARES_DO_NOT_SUM`. Each `ExpenseShare` row records the `expense_id` it belongs to, the `profile_id` who owes it, and the computed `share_cents`, with any remainder again assigned in ascending `created_at` order. An expense opens in `POSTED` status, and logging it recomputes every household member's `net_balance_cents` while keeping `ledger_sum_cents` at zero.

A posted expense can be reversed with a void, a compensating action that moves the expense from `POSTED` to `VOIDED` and undoes its ledger impact. Voiding recomputes the household's net balances and again leaves `ledger_sum_cents` at zero. A voided expense no longer contributes its payer's credit or its participants' obligations to anyone's net position.

### 3.7. Settling Up Between Roommates

When the ledger leaves one roommate owing another, they square accounts with a `Settlement`. A roommate proposes one by naming the `household_id`, the `from_profile_id` (the paying debtor), the `to_profile_id` (the receiving creditor), and an `amount_cents` strictly greater than zero. Both the payer and the receiver must be `ACTIVE` members of the named household, failing which the proposal is rejected with `ERR_NOT_HOUSEHOLD_MEMBER`, and the two parties must be distinct — a settlement whose `from_profile_id` equals its `to_profile_id` is rejected with `ERR_SELF_SETTLEMENT`. A new settlement opens in `PROPOSED`. The lifecycle runs `PROPOSED` to `CONFIRMED`, `DISPUTED`, or `CANCELLED`, where `CONFIRMED` and `CANCELLED` are terminal and `DISPUTED` can cycle back to `PROPOSED`.

Confirmation belongs to the creditor: the acting roommate must be the settlement's `to_profile_id`. The household must not be `FROZEN`, and the debtor's membership must be in `ACTIVE` or `MOVED_OUT` status. The confirm request must carry `expected_household_version` matching the household's current `version`; if another ledger write has advanced the household's `version` since the client last read it, the confirm is rejected with `ERR_STALE_HOUSEHOLD_VERSION` at HTTP 412. The settlement's `amount_cents` must not exceed the debtor's outstanding debt — the absolute value of the debtor's `net_balance_cents` when that balance is negative — and an amount that exceeds it is rejected with `ERR_SETTLEMENT_EXCEEDS_DEBT`; furthermore, confirming when the debtor has no outstanding debt at all (their `net_balance_cents` is zero or positive) is rejected with `ERR_NO_OUTSTANDING_DEBT`. On a successful confirm, the settlement moves to `CONFIRMED`, the debtor's `net_balance_cents` is increased by `amount_cents` (reducing their debt) while the creditor's `net_balance_cents` is decreased by the same `amount_cents` (reducing their credit), the household's `ledger_sum_cents` is recomputed and stays zero, the household's `version` is incremented by one, and any `SCHEDULED` payment reminder for this settlement is moved to `CANCELLED`.

A debtor who disagrees with a proposed settlement files a dispute against it; the filer must be the settlement's `from_profile_id`, the settlement must be `PROPOSED`, and filing moves the settlement to `DISPUTED` while opening a new dispute referencing it. Once that dispute closes, the creditor may re-propose: re-proposing carries the settlement from `DISPUTED` back to `PROPOSED`, but only when the linked dispute is `RESOLVED` or `REJECTED`, and if the dispute resolved with an adjustment, the settlement's `amount_cents` adopts the dispute's `adjusted_amount_cents`. Either the debtor or the creditor may cancel a `PROPOSED` settlement, moving it to the terminal `CANCELLED`.

### 3.8. Payment Reminders and the Clock

A roommate schedules a `PaymentReminder` for either a bill or a settlement. The reminder names the `household_id`, a `due_date`, and exactly one of `bill_id` or `settlement_id` — the other must be null. A reminder that names neither or both is rejected with `ERR_REMINDER_TARGET_AMBIGUOUS`. A reminder opens in `SCHEDULED`. When the reminder targets a bill and that bill's `reminder_status` is currently `NONE`, scheduling advances the bill's `reminder_status` to `SCHEDULED`; this reminder dimension moves independently of the bill's `payment_status`. A reminder for a bill may only be scheduled while the bill is not yet `PAID`.

Dispatch is driven by the server clock, which a `PlatformOperator` can advance to a supplied `to_iso8601` instant via a test-driving clock-setting capability. A separate operator-only dispatch capability runs the reminder batch: every `SCHEDULED` reminder whose `due_date` is at or before the current clock instant is moved to `SENT`, and where such a reminder targets a bill, that bill's `reminder_status` is advanced to `SENT` as well. A member who receives a reminder may acknowledge it, moving the reminder from `SENT` to `ACKNOWLEDGED`. A scheduled reminder may also reach `CANCELLED` — automatically when its bill is fully paid or its settlement is confirmed, as described above. The reminder's own `status` thus ranges over `SCHEDULED`, `SENT`, `ACKNOWLEDGED`, and `CANCELLED`.

### 3.9. Disputes, Adjudication, and the Freeze Cascade

A `Dispute` lets a roommate contest a charge. Filing one takes the `household_id`, the `filed_by_id` of the member raising it, a non-empty `reason`, and exactly one target — either an `expense_id` or a `settlement_id`, with the other null. A dispute opens in `OPEN` and travels through `UNDER_REVIEW` to the terminal `RESOLVED` or `REJECTED`, with a cyclic path back from `UNDER_REVIEW` to `OPEN`. When a dispute is filed against a settlement by that settlement's debtor, the settlement itself is driven to `DISPUTED` as described in the settlement workflow. The mediator-set `adjusted_amount_cents` is null until the dispute is resolved.

A `DisputeMediator` claims an `OPEN` dispute to begin review, provided they are not the dispute's `filed_by_id`. Claiming moves the dispute to `UNDER_REVIEW` and drives the household to `FROZEN`, sealing the ledger for the duration of review. From `UNDER_REVIEW` the mediator who claimed it may reopen the dispute back to `OPEN`; from `UNDER_REVIEW` the mediator (again, not the filer) may resolve it, and may reject it. Resolving sets the dispute to `RESOLVED` and records the `adjusted_amount_cents`; when the dispute targets an expense, an `adjusted_amount_cents` greater than zero must be supplied, and the targeted expense's `total_amount_cents` is reset to that adjusted amount, its `ExpenseShare` rows are recomputed, every member's `net_balance_cents` is recomputed, and `ledger_sum_cents` stays zero. Rejecting sets the dispute to `REJECTED` and leaves the target unchanged. Each of reopen, resolve, and reject ends the freeze: the household returns to `ACTIVE`, provided no other dispute is still `UNDER_REVIEW`. The segregation-of-duties rule governs all three adjudication actions — claim, resolve, and reject — so a mediator who happens to be the filer is turned away with `ERR_SELF_ADJUDICATION`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions and the test-driving clock and dispatch operations — return a `200 OK` status code. The request body, response body, and side effects of each endpoint are described in the workflow narratives of Section 3; the table below is only a routing summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/roommate-profiles` | Register a roommate profile | Roommate (unauthenticated allowed) |
| GET | `/roommate-profiles/{id}` | Fetch a roommate profile | Roommate, DisputeMediator, PlatformOperator |
| GET | `/roommate-profiles` | List roommate profiles | Roommate, DisputeMediator, PlatformOperator |
| GET | `/roommate-profiles/{id}/bill-splits` | List bill splits owed by this profile | Roommate, DisputeMediator, PlatformOperator |
| GET | `/roommate-profiles/{id}/expense-shares` | List expense shares owed by this profile | Roommate, DisputeMediator, PlatformOperator |
| POST | `/room-listings` | Create a room listing | Roommate |
| GET | `/room-listings/{id}` | Fetch a room listing | Roommate, DisputeMediator, PlatformOperator |
| GET | `/room-listings` | List room listings (filter by lister) | Roommate, DisputeMediator, PlatformOperator |
| POST | `/match-requests` | Apply to a listing | Roommate |
| GET | `/match-requests/{id}` | Fetch a match request | Roommate, DisputeMediator, PlatformOperator |
| GET | `/match-requests` | List match requests | Roommate, DisputeMediator, PlatformOperator |
| POST | `/match-requests/{id}/accept` | Lister accepts an application | Roommate |
| POST | `/match-requests/{id}/reject` | Lister rejects an application | Roommate |
| POST | `/match-requests/{id}/withdraw` | Applicant withdraws an application | Roommate |
| POST | `/match-requests/{id}/reapply` | Applicant re-applies after withdrawal | Roommate |
| GET | `/households/{id}` | Fetch a household | Roommate, DisputeMediator, PlatformOperator |
| GET | `/households` | List households (filter by manager/listing) | Roommate, DisputeMediator, PlatformOperator |
| GET | `/households/{id}/memberships` | List a household's memberships | Roommate, DisputeMediator, PlatformOperator |
| GET | `/households/{id}/bills` | List a household's bills | Roommate, DisputeMediator, PlatformOperator |
| GET | `/households/{id}/expenses` | List a household's expenses | Roommate, DisputeMediator, PlatformOperator |
| GET | `/households/{id}/settlements` | List a household's settlements | Roommate, DisputeMediator, PlatformOperator |
| GET | `/households/{id}/disputes` | List a household's disputes | Roommate, DisputeMediator, PlatformOperator |
| GET | `/memberships/{id}` | Fetch a membership | Roommate, DisputeMediator, PlatformOperator |
| GET | `/memberships` | List memberships (filter by profile/household) | Roommate, DisputeMediator, PlatformOperator |
| POST | `/memberships/{id}/activate` | Manager activates a pending membership | Roommate |
| POST | `/memberships/{id}/move-out` | Move a member out | Roommate |
| POST | `/bills` | Issue a bill for a household | Roommate |
| GET | `/bills/{id}` | Fetch a bill | Roommate, DisputeMediator, PlatformOperator |
| GET | `/bills/{id}/splits` | List a bill's splits | Roommate, DisputeMediator, PlatformOperator |
| POST | `/bills/{id}/record-payment` | Record a member's payment of their split | Roommate |
| POST | `/expenses` | Log a shared expense | Roommate |
| GET | `/expenses` | List expenses (filter by household/payer) | Roommate, DisputeMediator, PlatformOperator |
| GET | `/expenses/{id}` | Fetch an expense | Roommate, DisputeMediator, PlatformOperator |
| GET | `/expenses/{id}/shares` | List an expense's shares | Roommate, DisputeMediator, PlatformOperator |
| POST | `/expenses/{id}/void` | Void a posted expense | Roommate |
| POST | `/settlements` | Propose a settle-up payment | Roommate |
| GET | `/settlements` | List settlements (filter by household/parties) | Roommate, DisputeMediator, PlatformOperator |
| GET | `/settlements/{id}` | Fetch a settlement | Roommate, DisputeMediator, PlatformOperator |
| POST | `/settlements/{id}/confirm` | Creditor confirms a settlement | Roommate |
| POST | `/settlements/{id}/repropose` | Re-propose a disputed settlement | Roommate |
| POST | `/settlements/{id}/cancel` | Cancel a proposed settlement | Roommate |
| POST | `/payment-reminders` | Schedule a payment reminder | Roommate |
| GET | `/payment-reminders/{id}` | Fetch a payment reminder | Roommate, DisputeMediator, PlatformOperator |
| GET | `/payment-reminders` | List payment reminders | Roommate, DisputeMediator, PlatformOperator |
| POST | `/payment-reminders/{id}/acknowledge` | Acknowledge a sent reminder | Roommate |
| POST | `/disputes` | File a dispute over an expense or settlement | Roommate |
| GET | `/disputes/{id}` | Fetch a dispute | Roommate, DisputeMediator, PlatformOperator |
| GET | `/disputes` | List disputes | Roommate, DisputeMediator, PlatformOperator |
| POST | `/disputes/{id}/claim` | Mediator claims a dispute for review | DisputeMediator |
| POST | `/disputes/{id}/resolve` | Mediator resolves a dispute | DisputeMediator |
| POST | `/disputes/{id}/reject` | Mediator rejects a dispute | DisputeMediator |
| POST | `/disputes/{id}/reopen` | Mediator reopens a dispute | DisputeMediator |
| POST | `/_clock/set` | Set the server clock (test-driving) | PlatformOperator (unauthenticated allowed) |
| POST | `/_reminders/dispatch` | Dispatch due reminders (test-driving batch) | PlatformOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SELF_ADJUDICATION` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_HOUSEHOLD_FROZEN` | 409 |
| `ERR_NOT_HOUSEHOLD_MEMBER` | 422 |
| `ERR_SELF_SETTLEMENT` | 422 |
| `ERR_SHARES_DO_NOT_SUM` | 422 |
| `ERR_BILL_PERIOD_OVERLAP` | 409 |
| `ERR_INVALID_PERIOD` | 422 |
| `ERR_ROOM_AT_CAPACITY` | 409 |
| `ERR_OCCUPANCY_OVERLAP` | 409 |
| `ERR_SETTLEMENT_EXCEEDS_DEBT` | 422 |
| `ERR_NO_OUTSTANDING_DEBT` | 422 |
| `ERR_BELOW_MATCH_THRESHOLD` | 422 |
| `ERR_SELF_APPLICATION` | 422 |
| `ERR_EMAIL_TAKEN` | 409 |
| `ERR_REMINDER_TARGET_AMBIGUOUS` | 422 |
| `ERR_STALE_HOUSEHOLD_VERSION` | 412 |
| `ERR_VALIDATION` | 422 |
