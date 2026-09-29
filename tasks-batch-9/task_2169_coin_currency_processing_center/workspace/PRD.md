# Coin & Currency Processing Center API — Product Requirements Document

## 1. Introduction

A bank cash vault is the place where physical money stops being a customer's claim and starts being a book entry. Armored carriers arrive with tamper-sealed bags whose contents nobody has verified; tellers open, count and fitness-sort those contents on high-speed machines; suspect notes are pulled and reported; fit notes are bundled into cash letters and shipped to the Federal Reserve; and somewhere in the middle a depositor is given uncollected credit against money that has not actually been counted yet. Every one of those steps is a point where value can be lost, double-counted, or silently written off, which is why the processing floor runs on chain-of-custody records, dual control, and a settlement ledger that must reconcile in both directions.

This document specifies the API for a Coin & Currency Processing Center. The system tracks a deposit from the moment a courier lodges a manifest through sealed-bag custody hops, machine counting and fitness sorting, counterfeit reporting, the customer's discrepancy-claim window, final settlement against the depositor's account, Federal Reserve cash-letter reconciliation, and the parallel business of fulfilling coin and change orders out of the vault's own box inventory. Two things make this domain unusually demanding. First, money is credited twice on two different bases — once provisionally from what the customer *declared*, and once finally from what the machines actually *counted* — and the signed gap between those two numbers is itself a reportable figure. Second, the operations that move value are deliberately split between people: the operator who opens a counting session may not be the one who closes it, the manager who approves a coin order may not be the one who hands the boxes over, and the person whose count produced a variance may not be the person who rules on the customer's claim about it.

The API is mounted under `/cash-vault`. It is designed for deterministic, replayable operation: all time-sensitive behaviour reads from a server-held logical clock rather than wall-clock time, so counting windows, claim deadlines and count timestamps can be exercised precisely. Readers should treat §2 as the binding contract for envelopes, headers, precision and validation ordering, and §3 as the authoritative description of what each business operation actually does to the data.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to this API must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is absent, empty, or blank, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The same `ERR_UNAUTHENTICATED` rejection applies when `X-User-Role` carries a value that is not one of the six roles this system recognises.

The six roles are `VaultManager`, `VaultTeller`, `ArmoredCarrier`, `ComplianceOfficer`, `CustomerAccountHolder`, and `FederalReserveAgent`. A `VaultManager` runs the processing center: vault posture, coin inventory positions, deposit holds, settlements, discrepancy-claim decisions, Federal Reserve cash letters, and coin-order approvals. A `VaultTeller` works the floor: verifying drops, extending provisional credit, scheduling and running counting sessions, and releasing or taking back coin. An `ArmoredCarrier` is the courier crew that lodges the manifest, registers sealed bags, and records custody hops up to vault receipt. A `ComplianceOfficer` owns counterfeit detection and the reporting chain to the Secret Service. A `CustomerAccountHolder` is the depositing customer, who files discrepancy claims and statement-adjustment disputes and places coin and change orders. A `FederalReserveAgent` is the Federal Reserve counterparty that confirms cash letters and posts credit advices. When an authenticated caller's role is not listed among the roles permitted for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). §4 gives the authorized role or roles for every endpoint.

Five of the six roles carry an opaque identity. When `X-User-Role` is `VaultManager`, `VaultTeller`, `ArmoredCarrier`, `ComplianceOfficer`, or `FederalReserveAgent`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity; the server records it on resources where a transition captures the acting operator — as `carrier_courier_user_id` on a deposit ticket, `actor_user_id` on a custody event, `operator_user_id` and `verifier_user_id` on a counting session, `decided_by_user_id` on a discrepancy claim, and `approved_by_user_id` and `released_by_user_id` on a coin order — and compares it to other recorded operator identifiers for dual-control and segregation-of-duties purposes, but never compares it to any entity's `id`.

`CustomerAccountHolder` is different: it is entity-backed. When `X-User-Role` is `CustomerAccountHolder`, `X-User-ID` is the `id` of the acting `CustomerAccount`, and ownership checks on any resource that references a `CustomerAccount` compare that resource's account reference to `X-User-ID`. Concretely, a `CustomerAccountHolder` may only touch resources whose reachable customer account is its own: the account itself and its statement, a `CoinOrder` through `customer_account_id`, a `DiscrepancyClaim` through `customer_account_id`, a `DepositTicket` through `customer_account_id`, and a `SealedBag` through the `customer_account_id` of the deposit ticket the bag belongs to. This ownership check guards ten operations: reading one customer account, reading a customer statement, reading one deposit ticket, reading one sealed bag, filing a discrepancy claim, resubmitting a discrepancy claim, reading one discrepancy claim, placing a coin order, reading one coin order, and reading a coin order's lines. A mismatch is rejected with `ERR_ACCOUNT_OWNERSHIP` (HTTP 403).

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

All collection endpoints accept two optional query parameters. `limit` controls page size: it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100. `offset` controls the starting position: it defaults to 0 and its minimum accepted value is 0. A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, is a malformed query and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint narrative says otherwise, list results are sorted by `created_at` in ascending order — oldest first. For list responses the `meta` object carries `limit`, `offset`, `total_count` and `has_more` in addition to `api_request_id` and `api_request_timestamp`; `total_count` is the number of rows matching the filters before the page window is applied, and `has_more` is true exactly when rows remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and the Logical Clock

Every resource is identified by an `id` that the server mints as a UUID. Identifiers carry no type prefix and are never supplied by the client. Most resources also carry three further common properties: `created_at` and `updated_at`, both ISO 8601 UTC timestamps rendered with exactly three fractional-second digits, and `version`, an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row. `created_at` is fixed at creation and never changes; `updated_at` is refreshed on every mutation.

Two resource types are append-only records rather than mutable entities, and they carry only `id` and `created_at`. A `CustodyEvent` — one hop in a bag's chain of custody — has no `updated_at` and no `version`. A `CoinOrderLine` — one denomination line inside a coin order — likewise has no `updated_at` and no `version`, even though the values recorded on it are rewritten by the order's own approval and return transitions. All twelve other resource types (`Vault`, `CustomerAccount`, `DepositTicket`, `SealedBag`, `CountingMachine`, `CountSession`, `FitnessLot`, `CounterfeitReport`, `DiscrepancyClaim`, `FedDeposit`, `CoinOrder`, and `VaultInventory`) carry the full set of `id`, `created_at`, `updated_at`, and `version`.

Time in this system is not wall-clock time. The server holds a **logical clock**, and every deadline, occupancy window, and business timestamp — `counted_at`, `completed_at`, `filed_at`, `submitted_at`, `confirmed_at` — reads from it. Before the clock has ever been set, it reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. A `VaultManager` may advance or rewind the clock by supplying a `to_iso8601` instant; the response reports the new instant as `current_utc`, and no entity is mutated by the operation. Note that `created_at`, `updated_at` and the envelope's `api_request_timestamp` are ordinary server timestamps and are not governed by this logical clock.

### 2.5. Nested Retrieval and Referential Resolution

Several read endpoints are nested underneath a parent — a bag's custody events, a session's fitness lots, a cash letter's attached lots, a coin order's lines, a vault's inventory positions and its cash-letter reconciliation. Path identifiers are resolved strictly from left to right. The outer identifier is resolved first, and if it does not name an existing row the request fails immediately with that entity's not-found error without any inner identifier being examined. The not-found errors are entity-specific: `ERR_VAULT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_BAG_NOT_FOUND`, `ERR_MACHINE_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_FED_DEPOSIT_NOT_FOUND`, and `ERR_COIN_ORDER_NOT_FOUND`, all returning HTTP 404.

The same family of not-found errors covers foreign-key identifiers supplied inside a request body. Body references are resolved in the order the endpoint declares its input fields, so when a payload names two references that both fail to resolve, the earlier-declared field's error is the one returned. This body-reference resolution applies to the creation of deposit tickets, sealed bags, counting machines, count sessions, counterfeit reports, discrepancy claims, cash letters, and coin orders.

### 2.6. The Validation Ladder

Because many operations carry a dozen guards at once, the order in which those guards are evaluated is part of the contract. Checks are evaluated in the following sequence, and the first failure is the one reported; later checks are never reached.

1. **Authentication.** Both `X-User-ID` and `X-User-Role` present and non-blank — `ERR_UNAUTHENTICATED` (401).
2. **Role recognition.** `X-User-Role` names one of the six declared roles — `ERR_UNAUTHENTICATED` (401).
3. **Authorization.** The caller's role appears in the endpoint's permitted role list — `ERR_FORBIDDEN_ROLE` (403).
4. **Request shape.** Required fields present, types correct, enum members recognised, constrained integers non-negative, `limit` within 1 through 100 and `offset` at least 0, `window_end` strictly after `window_start`, `pickup_window_end` strictly after `pickup_window_start`, a coin order's `lines` array non-empty, and a count-completion's `lots` array non-empty — `ERR_INVALID_REQUEST` (400). One deliberate exception: an empty `fitness_lot_ids` array on a cash letter is **not** treated as a shape error here; it surfaces much later as `ERR_NO_ELIGIBLE_LOTS`.
5. **Path existence.** Every identifier embedded in the path resolves, left to right — the 404 family above.
6. **Body reference existence.** Every foreign-key identifier in the body resolves, in declared field order — the 404 family above.
7. **Account ownership.** For a `CustomerAccountHolder`, `X-User-ID` matches the customer account reachable from the target resource — `ERR_ACCOUNT_OWNERSHIP` (403).
8. **Optimistic concurrency.** The supplied expected-version value matches the parent's current `version` — `ERR_STALE_VERSION` (412).
9. **Transition legality.** The target entity is in a state from which the requested transition is declared — `ERR_INVALID_STATE` (409).
10. **Bag custody readiness** — `ERR_BAG_NOT_RECEIVED` (409).
11. **Declared bag count agreement at verification** — `ERR_BAG_COUNT_MISMATCH` (409).
12. **Bag counted before a claim may be filed** — `ERR_BAG_NOT_COUNTED` (409).
13. **Vault not frozen** — `ERR_VAULT_FROZEN` (409).
14. **Vault fully open for a physical coin release** — `ERR_VAULT_RESTRICTED` (409).
15. **Counting machine available** — `ERR_MACHINE_UNAVAILABLE` (409).
16. **Dual control** — `ERR_DUAL_CONTROL_VIOLATION` (409).
17. **Segregation of duties on claim decisions** — `ERR_SEGREGATION_OF_DUTIES` (409).
18. **No draft counterfeit report blocking a cash-letter shipment** — `ERR_COUNTERFEIT_REPORT_PENDING` (409).
19. **Machine type accepts bag type** — `ERR_MACHINE_TYPE_MISMATCH` (422).
20. **Counterfeit report agrees with its lot** — `ERR_REPORT_LOT_MISMATCH` (422).
21. **Named lots are eligible for a cash letter** — `ERR_LOT_NOT_ELIGIBLE` (422).
22. **Named lots belong to the cash letter's vault** — `ERR_LOT_VAULT_MISMATCH` (422).
23. **Machine occupancy window free** — `ERR_MACHINE_WINDOW_CONFLICT` (409).
24. **Counting window not in the past** — `ERR_WINDOW_IN_PAST` (422).
25. **Vault pickup capacity not exceeded** — `ERR_PICKUP_CAPACITY_EXCEEDED` (409).
26. **No duplicate denomination within one coin order** — `ERR_DUPLICATE_DENOMINATION` (422).
27. **Discrepancy claim filed inside the claim window** — `ERR_CLAIM_WINDOW_CLOSED` (422).
28. **Claim review-round ceiling not reached** — `ERR_CLAIM_ROUND_LIMIT` (409).
29. **Seal serial not already registered** — `ERR_DUPLICATE_SEAL` (409).
30. **Unique business identifiers do not collide** — `ERR_DUPLICATE_IDENTIFIER` (409).
31. **Observed seal matches the registered seal at vault receipt** — `ERR_SEAL_TAMPERED` (409).
32. **Cash-letter lot list non-empty after eligibility filtering** — `ERR_NO_ELIGIBLE_LOTS` (422).
33. **Reported lot breakdown reconciles with the reported totals** — `ERR_LOT_TOTAL_MISMATCH` (422).
34. **No material variance left open at settlement** — `ERR_MATERIAL_VARIANCE_UNRESOLVED` (409).
35. **Customer account active** — `ERR_ACCOUNT_SUSPENDED` (409).
36. **Coin inventory sufficient** — `ERR_INSUFFICIENT_COIN_INVENTORY` (409).
37. **Inventory adjustment does not go negative** — `ERR_INVENTORY_NEGATIVE` (422).
38. **Claimed amount within the bag's declared amount** — `ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED` (422).
39. **Resolution amount within the claimed amount** — `ERR_RESOLUTION_EXCEEDS_CLAIM` (422).

The practical consequence worth internalising is that state legality is decided *before* any business guard: an operation attempted from the wrong state reports `ERR_INVALID_STATE` even if a business guard would also have failed. Equally, concurrency is decided before state, so a stale expected-version value surfaces as `ERR_STALE_VERSION` even when the target entity is in a state that would have rejected the write anyway.

Each of these checks guards a specific set of operations. Bag custody readiness (`ERR_BAG_NOT_RECEIVED`) guards three: scheduling a count session, starting a count session, and verifying a deposit ticket. The frozen-vault check (`ERR_VAULT_FROZEN`) guards three: starting a count session, submitting a cash letter, and releasing a coin order. The restricted-vault check (`ERR_VAULT_RESTRICTED`) guards one: releasing a coin order. Dual control (`ERR_DUAL_CONTROL_VIOLATION`) guards two: completing a count session and releasing a coin order. Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`) guards two: approving a discrepancy claim and denying one. The suspended-account check (`ERR_ACCOUNT_SUSPENDED`) guards two: extending provisional credit on a deposit ticket and approving a coin order. Coin-inventory sufficiency (`ERR_INSUFFICIENT_COIN_INVENTORY`) guards two: approving a coin order and releasing one. The claimed-amount ceiling (`ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED`) guards two: filing a discrepancy claim and resubmitting one. The unique-identifier check (`ERR_DUPLICATE_IDENTIFIER`) guards five creations: vaults, customer accounts, deposit tickets, counting machines, and cash letters. The remaining checks each guard the single operation their narrative in §3 describes.

### 2.7. Money, Weight, and Rounding Discipline

Every monetary amount in this API is an integer number of cents; there are no fractional-cent fields and no floating-point currency. Coin weights are integer grams. Two derived values are decimals rather than integers: a customer's `risk_score` and a coin order's `fill_ratio_pct`, both carried to exactly 2 decimal places.

Wherever a computation must be reduced to a coarser unit, the rounding method is **round half up** — a value exactly at the midpoint rounds away from zero to the larger magnitude. Rounding is applied only at the points the calculation narratives in §3 explicitly name; intermediate values are carried at full precision until such a point is reached. Where a total is described as the sum of already-rounded components, that total is an exact integer sum and is never re-rounded.

### 2.8. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on the state it last observed, and both express that proof as an expected-version field naming the *parent* entity rather than the resource being written.

Creating a `CountSession` — the `POST /cash-vault/count-sessions` operation — requires `expected_sealed_bag_version` in the request body. This field is mandatory, not optional. Its value must equal the current `version` of the `SealedBag` named by `sealed_bag_id`. If the bag's `version` has advanced since the client last read it — a custody hop was appended, an earlier session was started, another session was scheduled — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The write is otherwise entirely legitimate, since a new session deliberately supersedes any prior scheduled session on the same bag; the version check is what pins *which* observed bag state the caller was scheduling against.

Releasing a `CoinOrder` — the `POST /cash-vault/coin-orders/{id}/release` operation — requires `expected_vault_version` in the request body, likewise mandatory. Its value must equal the current `version` of the `Vault` fulfilling the order. If the vault's `version` has advanced since the client last read it — an inventory adjustment, a posture change, another order's approval or release — the release is rejected with `ERR_STALE_VERSION` (HTTP 412). Release is legal from either approved state, so nothing in the order's own state rejects the write; the stale version is what captures that the vault's inventory position has moved under the caller.

No other endpoint accepts an expected-version field. Supplying one elsewhere has no effect, and omitting one on either of the two operations above is a request-shape failure.

### 2.9. Dual Control and Segregation of Duties

The processing floor runs on the principle that no single person may both create and consummate a movement of value. Three separate rules implement this.

When a counting session is completed, the acting `X-User-ID` must differ from the `operator_user_id` recorded when the session was created. A teller may open a session and a teller may close one, but not the same teller on the same session; a violation is `ERR_DUAL_CONTROL_VIOLATION`.

When a coin order is released, the acting `X-User-ID` must differ from the `approved_by_user_id` recorded at approval. The manager who authorised the allocation may not also be the person who hands the boxes to the carrier; a violation is again `ERR_DUAL_CONTROL_VIOLATION`.

When a discrepancy claim is approved or denied, the deciding `VaultManager`'s `X-User-ID` must differ from the `verifier_user_id` of the `COMPLETED` counting session whose `sealed_bag_id` matches the claim's disputed bag. The person whose count produced a variance may not rule on the customer's dispute about that count; a violation is `ERR_SEGREGATION_OF_DUTIES`.

### 2.10. Vault Posture as an Operating Gate

Each vault carries a `posture` that gates the operations its floor may perform. `OPEN` is the normal condition and permits everything. `RESTRICTED` continues to permit counting but blocks the physical release of coin. `FROZEN` blocks counting, cash-letter shipment, and coin release alike. Posture is set to `OPEN` when the vault is registered and thereafter changes only through the posture operation described in §3.

Where an operation reaches a vault indirectly, the gate still applies: starting a counting session reaches the vault through the counting machine the session occupies, and shipping a cash letter reaches it through the cash letter's own `vault_id`. Attempting a gated operation against a `FROZEN` vault is rejected with `ERR_VAULT_FROZEN`. Attempting to release coin from a `RESTRICTED` vault is rejected with `ERR_VAULT_RESTRICTED` — a distinct code, because the remedy differs.

### 2.11. Cascades, Bubble-Ups, and Compensating Reversals

Many operations in this system touch more than one row. When a count completes, the effects propagate from the counting session to the bag, from the bag to the deposit ticket, and — when the ticket has no uncounted bag remaining — into an automatic ticket transition. When a counterfeit report is submitted, the effects propagate from the fitness lot to the counting session, to the bag, to the deposit ticket, and on to the customer account's risk figures. Each such propagation is spelled out in the workflow narratives of §3, and none of them are optional: an implementation that performs only the primary write is incomplete.

Every mutation of a row refreshes that row's `updated_at` and increments its `version` by 1, including mutations that arrive as a cascade from another entity's operation rather than as a direct request. Where a narrative in §3 calls out a version increment explicitly — a bag's `version` rising on each custody hop and on each counting transition, a vault's `version` rising on each posture change, inventory adjustment, coin-order approval, release and return — that call-out is a reminder of a rule that already applies, and is highlighted because those particular counters are what the optimistic-concurrency checks in §2.8 compare against.

Three operations exist purely to unwind an earlier one, and each is expected to leave the affected aggregates exactly as they were before. Reversing a provisional credit restores the customer's available funds to their pre-credit figure. Returning a released coin order restores both the vault's physical box position and the customer's ledger balance. Returning a submitted counterfeit report for correction restores the seized value to the bag and the session, and restores the customer's counterfeit incident count. In each case the compensating operation must move exactly the amounts the original operation moved.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Processing Center

Everything in this system hangs off a **vault** — a physical processing center. A `VaultManager` registers one by supplying a `vault_code`, which is a human-readable center code of between 1 and 32 characters that must be unique across all vaults, and a `name` for display. The manager may also supply `pickup_concurrency_limit`, the maximum number of coin-order pickup windows whose closed intervals may cover any single instant on this vault's dock; when omitted it defaults to 2, and it must be at least 1. A newly registered vault comes up with `posture` set to `OPEN`, `version` at 1, `cash_letter_adjustment_cents` at 0 and `coin_face_value_on_hand_cents` at 0. A `vault_code` that collides with an existing vault is rejected with `ERR_DUPLICATE_IDENTIFIER`.

Posture moves under manager control and only under manager control. The manager supplies the target `posture` value, and five moves are legal: `OPEN → RESTRICTED`, `RESTRICTED → FROZEN`, `OPEN → FROZEN`, `FROZEN → OPEN`, and `RESTRICTED → OPEN`. Note that the return path is cyclic and direct — a frozen vault reopens straight to `OPEN` without passing through `RESTRICTED`. Any other combination, including a request that names the posture the vault is already in, is rejected with `ERR_INVALID_STATE`. Each successful posture move increments the vault's `version` by 1, which is precisely why a client holding an expected vault version can be invalidated by a supervisor freezing the floor.

Coin sits in the vault as boxes, tracked one row per denomination in a **vault inventory position**. There is at most one position per pair of vault and `denomination`, and the recognised denominations are `PENNY`, `NICKEL`, `DIME`, and `QUARTER`. A manager moves a position by applying a signed `delta_boxes` to a named `denomination`; this single operator surface covers opening balances, armored replenishment, and shrinkage write-downs. If no position exists yet for that pair it is created on first use with `on_hand_boxes`, `reserved_boxes` and `available_boxes` all at 0, and the adjustment is then applied to that fresh row. The delta is applied to `on_hand_boxes`, and `available_boxes` is then recomputed as `on_hand_boxes` minus `reserved_boxes`, floored at 0 so it never goes negative. An adjustment that would drive `on_hand_boxes` below zero is refused outright with `ERR_INVENTORY_NEGATIVE`; the row is left untouched. `reserved_boxes` is never moved by an adjustment — it tracks boxes committed to approved-but-unreleased coin orders, it only ever moves through the coin-order lifecycle, and after a shrinkage write-down it may legitimately exceed `on_hand_boxes`. Every adjustment also recomputes the vault's `coin_face_value_on_hand_cents` and increments the vault's `version` by 1.

That `coin_face_value_on_hand_cents` figure is the vault's coin position expressed in money. It is the sum, over every one of the vault's inventory positions, of `on_hand_boxes` multiplied by the face value of a standard box of that denomination. A standard box is worth 2,500 cents of pennies (twenty-five dollars), 10,000 cents of nickels (one hundred dollars), 25,000 cents of dimes (two hundred and fifty dollars), or 50,000 cents of quarters (five hundred dollars). It is recomputed on every inventory mutation, whatever the source. Managers and tellers can read the vault's positions as a list, optionally narrowed to a single `denomination`, and paged with `limit` and `offset`.

Counting equipment is registered separately. A manager commissions a machine on a vault floor by naming the `vault_id` it sits on, a `machine_code` that must be unique across all machines, and a `machine_type` of `CURRENCY_SORTER`, `COIN_COUNTER`, or `MIXED_PROCESSOR`. The machine's `status` may be supplied at commissioning and defaults to `AVAILABLE`; the only other recognised value is `MAINTENANCE`. A duplicate `machine_code` is `ERR_DUPLICATE_IDENTIFIER`. Machines can be read individually or listed, filtered by `vault_id` and by `status`, with `limit` and `offset` paging.

Depositor accounts are opened by a manager against an `account_number` unique across all accounts, together with the depositor's legal `customer_name`. Two optional enum inputs shape the account: `tier`, which is `PREMIUM`, `STANDARD` or `WATCH` and defaults to `STANDARD`, and `status`, which is `ACTIVE` or `SUSPENDED` and defaults to `ACTIVE`. Account standing is written only at creation; nothing in this API moves an account between `ACTIVE` and `SUSPENDED` afterwards, but a `SUSPENDED` account still blocks provisional credit and coin-order approval with `ERR_ACCOUNT_SUSPENDED`. A duplicate `account_number` is `ERR_DUPLICATE_IDENTIFIER`. A freshly opened account starts with `ledger_balance_cents`, `provisional_credit_cents`, `available_balance_cents`, `denied_claim_count`, `counterfeit_incident_count` and `hold_count` all at 0, `risk_score` at 100.00 and `risk_grade` at `A`.

Of the account's money fields, `ledger_balance_cents` holds collected funds and moves only on deposit settlement and on coin-order release and return; `provisional_credit_cents` holds uncollected funds extended against tickets currently in provisional-credit or settlement-ready condition; and `available_balance_cents` is a derived identity that must always equal `ledger_balance_cents` plus `provisional_credit_cents`. The three counters are audit tallies: `denied_claim_count` is the number of this account's discrepancy claims that ended in `DENIED`, `counterfeit_incident_count` is the number of currently-`SUBMITTED` counterfeit reports reachable from this account's bags, and `hold_count` is the number of this account's deposit tickets that have entered `HELD` at least once.

### 3.2. The Armored Drop and the Chain of Custody

An armored crew begins a deposit by lodging an **intake ticket**. The `ArmoredCarrier` supplies the `customer_account_id` of the depositor being credited, the `vault_id` of the processing center receiving the drop, the `courier_manifest_number` covering the run — unique across all deposit tickets, and a collision is `ERR_DUPLICATE_IDENTIFIER` — and `declared_bag_count`, the number of sealed bags the carrier claims belong to this ticket, which must be at least 1. The ticket is created in `INTAKE`, its `carrier_courier_user_id` captured from the caller's `X-User-ID`, and every computed money field — `declared_total_cents`, `counted_total_cents`, `processing_fee_total_cents`, `provisional_credit_cents`, `final_settlement_cents`, `settlement_delta_cents` — and the counter `material_variance_open_count` all starting at 0, with `hold_reason` null. Tickets can be read one at a time or listed with optional `customer_account_id`, `vault_id` and `status` filters alongside `limit` and `offset`.

Each physical bag is then registered against the ticket. The carrier supplies the `deposit_ticket_id` it belongs to, the tamper-evident `seal_number` applied to it, which must be unique across all sealed bags — a repeat is `ERR_DUPLICATE_SEAL` — and a `bag_type` of `CURRENCY`, `COIN`, or `MIXED`, which determines what class of machine may later process it. The declared contents follow: `declared_amount_cents`, the amount the customer wrote on the bag manifest, which may be zero but not negative; and optionally `declared_note_count` and `declared_coin_weight_grams`, both defaulting to 0. A newly registered bag starts every computed field at zero — `counted_amount_cents`, `counted_note_count`, `counted_coin_weight_grams`, `variance_cents`, `processing_fee_cents`, `seized_amount_cents`, `claim_adjustment_cents` and `settlement_amount_cents` all at 0, `materiality_flag` false, and `counted_at` null. Registering a bag recomputes the parent ticket's `declared_total_cents` as the sum of `declared_amount_cents` across every bag carrying that `deposit_ticket_id`.

A bag carries **two independent state axes on the same row**, and this is the single most important structural fact about it. The custody axis, `custody_status`, runs `SEALED → IN_TRANSIT → VAULT_RECEIVED → OPENED` and records where the bag physically is. The counting axis, `count_status`, runs `PENDING → COUNTING → COUNTED → ADJUSTED` and records how far its contents have been processed. A newly registered bag is `SEALED` on the custody axis and `PENDING` on the counting axis. Neither axis constrains the other's ordering; the only coupling between them is the explicit guards named below. Bags can be read individually or listed with optional `deposit_ticket_id`, `custody_status` and `count_status` filters and the usual `limit` and `offset`.

The custody axis advances only by appending **custody events**, one hop at a time. Each hop names an `event_type`, a `location_code` for the site where it occurred, and an `observed_seal_number` — the serial actually read off the bag at that moment. The server records the acting `X-User-ID` as `actor_user_id`, assigns `sequence_no` as the 1-based position of this event within the bag's chain when the chain is ordered by `created_at` ascending, and computes `seal_intact` as true exactly when `observed_seal_number` equals the bag's registered `seal_number` and false otherwise. Custody events are append-only records; they may be read back as an ordered chain, paged by `limit` and `offset`, but never modified.

Four hop types drive four custody moves. A `PICKUP` hop, recorded by the carrier, moves a bag `SEALED → IN_TRANSIT`. A `TRANSFER` hop, also carrier-recorded, is a self-loop, `IN_TRANSIT → IN_TRANSIT`, and any number of transfer hops may be recorded while the bag is in transit. A `VAULT_RECEIPT` hop, recorded by a `VaultTeller`, moves the bag `IN_TRANSIT → VAULT_RECEIVED`, and this is the hop where the seal is legally read: the supplied `observed_seal_number` must equal the bag's `seal_number`, and a mismatch is refused with `ERR_SEAL_TAMPERED`, so a receipt hop that succeeds always records `seal_intact` as true. An `OPEN` hop, also teller-recorded, moves the bag `VAULT_RECEIVED → OPENED`, and it is permitted only when a counting session for that bag already exists in `SCHEDULED` condition; opening a bag with no scheduled count is refused with `ERR_INVALID_STATE`. An `OPEN` hop leaves the counting axis alone — the bag remains `PENDING`. Each of these four hops increments the bag's `version` by 1, and a hop whose type does not match the bag's current custody position — a `PICKUP` on an already-received bag, for instance — is `ERR_INVALID_STATE`.

Once every bag on the manifest is physically in the vault, a teller **verifies** the drop, moving the ticket `INTAKE → VERIFIED`. Two conditions gate it. The number of registered bags carrying this `deposit_ticket_id` must equal the ticket's `declared_bag_count`; a short or long drop is `ERR_BAG_COUNT_MISMATCH`. And every one of those bags must have reached `VAULT_RECEIVED` on its custody axis; a bag still `SEALED` or `IN_TRANSIT` makes the verification `ERR_BAG_NOT_RECEIVED`. Verification recomputes `declared_total_cents` from the bags as its side effect, so the figure the credit decision reads is the one the vault actually holds.

### 3.3. Uncollected Funds: Provisional Credit, Holds, and Reversal

A verified ticket sits at a fork with two mutually exclusive branches, and the branch taken is a judgement about the depositor rather than about the money. Branch A extends **provisional credit** — uncollected funds made available to the customer before a single note has been counted — and moves the ticket `VERIFIED → PROVISIONAL_CREDITED`. Branch B places a **hold** instead, moving the ticket `VERIFIED → HELD`, extends nothing, and moves no balance field on the customer account at all. Both branches leave the counting work still to be done, and both eventually converge on settlement readiness.

Provisional credit is extended by a `VaultTeller` and takes no request body; everything it needs is already on the ticket and the account. The depositor's account `status` must be `ACTIVE` — extending credit to a `SUSPENDED` account is `ERR_ACCOUNT_SUSPENDED`. The amount is computed as follows. First, add up `declared_amount_cents` across every bag on this ticket whose custody axis reads `VAULT_RECEIVED` or `OPENED`; bags still in transit or still sealed contribute nothing to this figure. Second, select the availability haircut from the depositor's `tier`: a `PREMIUM` depositor takes no haircut at all, a `STANDARD` depositor takes a two percent haircut, and a `WATCH` depositor takes a five percent haircut. Third, multiply the eligible declared total by one minus that haircut fraction — so `PREMIUM` keeps the whole amount, `STANDARD` keeps ninety-eight hundredths of it, and `WATCH` keeps ninety-five hundredths of it — and round the product half up to a whole number of cents. Fourth, take the smaller of that rounded figure and the hard provisional cap of 5,000,000 cents, which is fifty thousand dollars; the cap wins whenever the rounded figure is larger. The result is written to the ticket's `provisional_credit_cents`. No processing fee is deducted at this stage, and no seizure or claim adjustment is visible yet, because none has happened.

Extending credit adds the ticket's `provisional_credit_cents` to the customer account's own `provisional_credit_cents` and then recomputes the account's `available_balance_cents` as `ledger_balance_cents` plus `provisional_credit_cents`. The account's `ledger_balance_cents` does not move — the funds are uncollected, and that distinction is the whole point of the field pair.

Placing a hold is a `VaultManager` decision and requires a free-text `hold_reason`, which is recorded on the ticket; the field is null until a hold is placed. A hold also increments the account's `hold_count` by 1. Nothing else moves: no credit is extended, and no balance field on the customer account changes on this branch.

Provisional credit can be withdrawn again. A `VaultManager` reversing it supplies a `reason` for the file and moves the ticket `PROVISIONAL_CREDITED → VERIFIED`, which is to say back to the fork. The reversal subtracts the ticket's `provisional_credit_cents` from the account's `provisional_credit_cents`, then sets the ticket's own `provisional_credit_cents` to 0, then recomputes the account's `available_balance_cents` as `ledger_balance_cents` plus `provisional_credit_cents`. Because the reversal removes exactly what the extension added, a customer's available funds after an extend-then-reverse pair are identical to what they were before the extension, and the ticket is once again eligible for either branch of the fork.

### 3.4. Counting: Machine Windows, Dual Control, and the Count Cascade

Counting is booked before it is performed. A `VaultTeller` schedules a **counting session** by naming the `sealed_bag_id` to be counted, the `counting_machine_id` to be occupied, the inclusive `window_start` and the exclusive `window_end` of the declared occupation, and `expected_sealed_bag_version` carrying the bag `version` the teller last observed. The session is created in `SCHEDULED` with `operator_user_id` captured from the caller's `X-User-ID`, `verifier_user_id` and `completed_at` null, and `counted_amount_cents`, `counted_note_count`, `counted_coin_weight_grams` and `seized_face_value_cents` all at 0.

Scheduling carries the densest guard set in the system. The bag's custody axis must have reached `VAULT_RECEIVED`; a bag still `SEALED` or `IN_TRANSIT` is `ERR_BAG_NOT_RECEIVED`. The machine's `machine_type` must accept the bag's `bag_type`: a `CURRENCY_SORTER` accepts only `CURRENCY` bags, a `COIN_COUNTER` accepts only `COIN` bags, and a `MIXED_PROCESSOR` accepts all three of `CURRENCY`, `COIN` and `MIXED`; note in particular that a `MIXED` bag can only ever go on a `MIXED_PROCESSOR`. A mismatch is `ERR_MACHINE_TYPE_MISMATCH`. The machine must not be double-booked: take the requested occupation as the interval beginning at `window_start` and ending 15 minutes after `window_end` — a quarter-hour cleaning buffer is appended to every declared window's end, never to its start — and treat that interval as half-open, including its start instant and excluding its end instant. That extended interval must not intersect the identically extended interval of any other session on the same `counting_machine_id` that is currently `SCHEDULED` or `IN_PROGRESS`; an intersection is `ERR_MACHINE_WINDOW_CONFLICT`. Because both intervals are half-open, a session whose extended interval ends exactly where another's begins does not conflict. Finally, `window_start` must be at or after the logical clock's current instant; a window that starts in the past is `ERR_WINDOW_IN_PAST`. When several of these fail together, the validation ladder in §2.6 decides which is reported: the stale-version check first, then machine-type compatibility, then window conflict, then the past-window check.

Scheduling a session deliberately **supersedes** any earlier session on the same bag: every prior session for that `sealed_bag_id` still sitting in `SCHEDULED` moves `SCHEDULED → SUPERSEDED`, releasing its hold on its machine window. Superseding changes nothing on the bag or the ticket — no field on either row moves as a result — and a `SUPERSEDED` session is terminal and can no longer be started or completed. Creating the new session increments the bag's `version` by 1, which is why two sessions cannot be scheduled back-to-back against the same observed bag version. Sessions can be read singly or listed, filtered by `sealed_bag_id`, `counting_machine_id` and `status`, with `limit` and `offset`.

Starting a session moves it `SCHEDULED → IN_PROGRESS` and simultaneously moves the bag's counting axis `PENDING → COUNTING`, incrementing the bag's `version` by 1. Three conditions gate the start: the bag must be `OPENED` on its custody axis, since the physical bag has to be cut open to be counted — anything less is `ERR_BAG_NOT_RECEIVED`; the bound machine's `status` must be `AVAILABLE`, and a machine in `MAINTENANCE` yields `ERR_MACHINE_UNAVAILABLE`; and the vault the machine sits on must not be `FROZEN`, which yields `ERR_VAULT_FROZEN`. A `RESTRICTED` vault still permits counting.

Completing the session is where the system's deepest cascade fires, and it must be done by a different person than started it: the acting `X-User-ID` must differ from the session's `operator_user_id`, or the request is `ERR_DUAL_CONTROL_VIOLATION`. The completing teller reports the machine's readings — `counted_amount_cents`, `counted_note_count`, `counted_coin_weight_grams` — together with a non-empty `lots` array giving the fitness-sorted breakdown. Each entry in `lots` carries a `category` of `FIT`, `UNFIT`, or `COUNTERFEIT_SUSPECT`, a `denomination_cents` giving the face value of one note in that lot, and a `note_count` of at least one note. The breakdown must reconcile with the totals in two ways at once: the sum over all lot entries of `denomination_cents` multiplied by `note_count` must equal the reported `counted_amount_cents`, and the sum of `note_count` across all lot entries must equal the reported `counted_note_count`. Either failure is `ERR_LOT_TOTAL_MISMATCH`.

On success the session moves `IN_PROGRESS → COMPLETED`, records the acting `X-User-ID` as `verifier_user_id`, and stamps `completed_at` from the logical clock. One **fitness lot** is created per entry in `lots`, each carrying its `count_session_id`, its `category`, its `denomination_cents` and `note_count`, a computed `face_value_cents` equal to `denomination_cents` multiplied by `note_count`, and a null `fed_deposit_id`. Initial lot disposition depends on category: `FIT` and `UNFIT` lots are created in `PENDING_DEPOSIT`, ready to be bundled into a Federal Reserve cash letter, while `COUNTERFEIT_SUSPECT` lots are created in `PENDING_REVIEW`, held back for the compliance chain. Lots are cascade-created and are not directly creatable; reading a session's fitness lots — optionally filtered by `category` and `status`, paged with `limit` and `offset` — is the only discovery channel for them.

The first cascade hop lands on the bag. Its `counted_amount_cents`, `counted_note_count` and `counted_coin_weight_grams` are copied from the session's reported readings, and `counted_at` is stamped with the same logical-clock instant, opening the customer's claim window. The bag's `variance_cents` is computed as `counted_amount_cents` minus `declared_amount_cents` and is signed, so a short bag is negative and a long bag positive. This variance is frozen at this moment: a later claim adjustment does **not** rewrite it. The `materiality_flag` is set true when the absolute value of `variance_cents` is at least 2,500 cents — a twenty-five dollar swing in either direction — and false otherwise. The per-bag processing fee is computed as described below and written to `processing_fee_cents`. The bag's `settlement_amount_cents` is then recomputed as `counted_amount_cents` plus `claim_adjustment_cents` minus `seized_amount_cents`; at this point both of those latter fields are still 0, but the same three-term recomputation is re-run every time any one of them changes. The bag's counting axis moves `COUNTING → COUNTED` and its `version` increments by 1.

The **per-bag processing fee** starts from a base charge of 250 cents for handling any bag at all. To that is added a per-note charge: each counted note costs 35 millicents, which is thirty-five thousandths of one cent, so the note component is the bag's `counted_note_count` multiplied by 35 and then divided by 1,000. To that is added a coin-weight charge of 180 cents per kilogram, where the kilogram figure is the bag's `counted_coin_weight_grams` divided by 1,000 and is *not* rounded before the multiplication. Finally, a mixed-handling surcharge of 125 cents is added when and only when the bag's `bag_type` is `MIXED`; `CURRENCY` and `COIN` bags add nothing here. That raw figure is then rounded half up to a whole number of cents and stored as the bag's `processing_fee_cents`. The order matters and is not interchangeable: each bag is rounded on its own, **before** any summation. The ticket's `processing_fee_total_cents` is the exact integer sum of the already-rounded `processing_fee_cents` of every bag on that ticket whose counting axis reads `COUNTED` or `ADJUSTED`, and that sum is never re-rounded. Bags still `PENDING` or `COUNTING` contribute nothing to it. Rounding each bag first and summing afterwards can exceed the sum-then-round figure by one cent for every pair of bags whose raw fee lands exactly on a half-cent, and the per-bag order is the one this system uses.

The second cascade hop lands on the deposit ticket. Its `counted_total_cents` is recomputed as the sum of `settlement_amount_cents` over every bag on the ticket whose counting axis reads `COUNTED` or `ADJUSTED`, and its `processing_fee_total_cents` is recomputed as just described. If the bag that just finished was flagged material, the ticket's `material_variance_open_count` is incremented by 1; that counter tracks bags with `materiality_flag` true whose counting axis is still `COUNTED` — that is, neither adjusted by an approved claim nor released by a denied one.

The third cascade hop is the ticket's own automatic transition. Once no bag on the ticket remains outside `COUNTED` or `ADJUSTED`, the ticket moves itself to `SETTLEMENT_READY`. This auto-transition fires from whichever of the three pre-count states the ticket happens to be in — `VERIFIED → SETTLEMENT_READY`, `PROVISIONAL_CREDITED → SETTLEMENT_READY`, or `HELD → SETTLEMENT_READY` — and in all three cases the accompanying effect is the same recomputation of `counted_total_cents` and `processing_fee_total_cents`. No actor drives this transition; it is a consequence of the last bag finishing its count. A ticket whose bags are not all finished simply stays where it is.

### 3.5. Counterfeit Detection and the Secret Service Chain

Notes the sorter flags as suspect never enter the Federal Reserve stream. A `ComplianceOfficer` drafts a **counterfeit report** against a lot by naming the `fitness_lot_id`, the `serial_number` recorded on the suspect note batch, and the `denomination_cents` and `note_count` the filer asserts for the batch. The report is created in `DRAFT` with `seized_face_value_cents` computed as `denomination_cents` multiplied by `note_count`, and with `submitted_at`, `case_number` and `correction_note` all null. Reports may be read singly or listed, filtered by `fitness_lot_id` and `status`, with `limit` and `offset`.

Submitting the report moves it `DRAFT → SUBMITTED` and is where value actually leaves the deposit. Two conditions gate it beyond the state check: the referenced lot must still be in `PENDING_REVIEW`, and a lot in any other disposition makes the submission `ERR_INVALID_STATE`; and the filer's assertions must match the lot exactly — the report's `denomination_cents` must equal the lot's `denomination_cents` and the report's `note_count` must equal the lot's `note_count`, with any difference rejected as `ERR_REPORT_LOT_MISMATCH`. On success `submitted_at` is stamped from the logical clock and a four-hop cascade runs. First, the lot moves `PENDING_REVIEW → SEIZED`. Second, because the lot was seized, the lot's counting session's `seized_face_value_cents` and the bag's `seized_amount_cents` both increase by the lot's `face_value_cents`, and the bag's `settlement_amount_cents` is recomputed as `counted_amount_cents` plus `claim_adjustment_cents` minus `seized_amount_cents` — so the seizure reduces what the customer will ultimately be paid. Third, because the bag's settlement amount changed, the deposit ticket's `counted_total_cents` is recomputed. Fourth, because the ticket total changed, the depositor's `counterfeit_incident_count` is incremented by 1 and the persisted risk figures are recomputed by re-running the `SETTLED_ONLY` view of the risk model described in §3.7 onto the account's `risk_score` and `risk_grade`.

A submitted report can be sent back. Returning it for correction requires a `correction_note` giving the reason, moves the report `SUBMITTED → DRAFT`, writes the note, and clears `submitted_at` back to null. Every seizure effect is unwound symmetrically: the lot moves `SEIZED → PENDING_REVIEW`; the bag's `seized_amount_cents` and the session's `seized_face_value_cents` each decrease by the lot's `face_value_cents`; the bag's `settlement_amount_cents` and the ticket's `counted_total_cents` are recomputed from the restored figures; and the depositor's `counterfeit_incident_count` is decremented by 1 with the `SETTLED_ONLY` risk view re-run onto `risk_score` and `risk_grade`. Because the report returns to `DRAFT` rather than to a terminal state, the cycle `DRAFT → SUBMITTED → DRAFT` may repeat, and the compensating effects are what keep the counting session's note-count conservation intact across the cycle.

The chain ends when the Secret Service responds. Acknowledging a submitted report requires the `case_number` they issued, records it, and moves the report `SUBMITTED → ACKNOWLEDGED`, which is terminal. An acknowledged report leaves the lot seized and moves no money — the value was already removed at submission.

One further consequence reaches outside this workflow: while any report on a lot sits in `DRAFT`, the cash letter covering that lot's counting session cannot be shipped, as §3.8 describes.

### 3.6. The Discrepancy Claim Window

When a machine count disagrees with what a customer believed was in the bag, the customer gets a bounded opportunity to say so. A `CustomerAccountHolder` files a **discrepancy claim** by naming the disputed `sealed_bag_id`, a `claim_type`, and the `claimed_amount_cents` they assert is missing, which must be at least 1 cent. The `claim_type` selects which grievance the same row expresses: `COUNT_VARIANCE` disputes the machine count itself, while `STATEMENT_ADJUSTMENT` disputes a settlement adjustment already posted to the account. Both types run through the identical lifecycle and the identical decision rules.

Three conditions gate filing. The bag must actually have been counted — its counting axis must read `COUNTED` or `ADJUSTED`, and a bag still `PENDING` or `COUNTING` yields `ERR_BAG_NOT_COUNTED`. The claim window must still be open: the logical clock's current instant must be strictly earlier than the bag's `counted_at` plus 24 hours, so a customer has one full day from the moment the count completed. The window is half-open, meaning that filing at exactly the 24-hour boundary is already too late and is rejected with `ERR_CLAIM_WINDOW_CLOSED`. And the amount asserted must not exceed the bag's own `declared_amount_cents`; a customer cannot claim more than they said was in the bag, and an over-claim is `ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED`.

A filed claim is created in `SUBMITTED` with `review_round` at 1, `filed_at` stamped from the logical clock, `resolution_amount_cents` at 0, and `decided_by_user_id`, `info_request_note` and `denial_reason` all null. Its `customer_account_id` is not supplied by the filer — it is copied from the `customer_account_id` of the deposit ticket that owns the disputed bag, which is also the value the ownership check in §2.1 compares against. Claims may be read singly or listed, filtered by `sealed_bag_id`, `customer_account_id` and `status`, with `limit` and `offset`.

An open claim can bounce between the manager and the customer. A `VaultManager` who needs more evidence supplies an `info_request_note` and moves the claim `SUBMITTED → INFO_REQUESTED`, recording the note. The customer answers by resubmitting with a revised `claimed_amount_cents`, which moves the claim `INFO_REQUESTED → SUBMITTED`, replaces the stored amount with the revised one, and increments `review_round` by 1. Two guards bound the loop. The revised amount is subject to the same ceiling as the original — it may not exceed the bag's `declared_amount_cents`, or the resubmit is `ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED`. And the cycle is capped at three review rounds: a resubmit is accepted only while `review_round` is strictly less than 3, so a claim already on its third round cannot go around again and the attempt is rejected with `ERR_CLAIM_ROUND_LIMIT`.

Both terminal decisions are made by a `VaultManager`, and both are blocked for one particular manager: whoever holds the `verifier_user_id` on the `COMPLETED` counting session for the disputed bag may not decide the claim, and an attempt yields `ERR_SEGREGATION_OF_DUTIES`. Either decision may be taken only from `SUBMITTED`; a claim currently sitting in `INFO_REQUESTED` must come back first.

**Approving** the claim moves it `SUBMITTED → APPROVED` and requires a `resolution_amount_cents` that does not exceed the claim's current `claimed_amount_cents` — a manager may grant less than was asked but never more, and an over-grant is `ERR_RESOLUTION_EXCEEDS_CLAIM`. The granted amount is stored on the claim and the deciding `X-User-ID` is recorded as `decided_by_user_id`. Three cascade hops follow. First, the bag's `claim_adjustment_cents` is set to the granted `resolution_amount_cents` and the bag's counting axis moves `COUNTED → ADJUSTED`, incrementing the bag's `version` by 1. Second, because the bag was adjusted, its `settlement_amount_cents` is recomputed as `counted_amount_cents` plus `claim_adjustment_cents` minus `seized_amount_cents`, and the deposit ticket's `counted_total_cents` is recomputed from the bags. Note that the bag's `variance_cents` is deliberately left alone — it remains the frozen record of what the machine found. Third, if the bag carried `materiality_flag` true, the ticket's `material_variance_open_count` is decremented by 1, because that flagged bag has now left `COUNTED`.

**Denying** the claim moves it `SUBMITTED → DENIED`, requires a `denial_reason` which is recorded, and records the deciding `X-User-ID` as `decided_by_user_id`. No money field on the bag moves at all — `claim_adjustment_cents` stays where it was and the bag's counting axis stays at `COUNTED`. Two things do move: the depositor's `denied_claim_count` is incremented by 1, which feeds directly into the risk model, and, if the bag carried `materiality_flag` true, the ticket's `material_variance_open_count` is decremented by 1. That second effect is the important one — denial releases the settlement block just as approval does, it simply does so without paying anything.

### 3.7. Settlement, Final Credit, and the Customer Statement

A ticket that has reached `SETTLEMENT_READY` is the vault's promise that every bag has been counted and every dispute closed. A `VaultManager` settles it, moving the ticket `SETTLEMENT_READY → SETTLED`, which is terminal. Exactly one business guard stands in the way: the ticket's `material_variance_open_count` must be 0. While even one flagged bag sits unresolved — neither adjusted by an approved claim nor released by a denied one — the settlement is refused with `ERR_MATERIAL_VARIANCE_UNRESOLVED`.

Settlement computes the **final credit**, which uses a completely different basis than the provisional credit did. Step one: add up `settlement_amount_cents` across every bag on this ticket whose counting axis reads `COUNTED` or `ADJUSTED`, giving the gross counted figure. This basis is what the machines actually found, plus any approved claim adjustment, minus any counterfeit seizure; it ignores every declared field. Step two: select the volume discount from that gross figure. A gross of at least 10,000,000 cents — one hundred thousand dollars — earns a twenty percent discount on the processing fee. Otherwise, a gross of at least 2,500,000 cents — twenty-five thousand dollars — earns a ten percent discount. Below that, there is no discount. Both comparisons are inclusive, so a gross landing exactly on 2,500,000 cents earns the ten percent band and a gross landing exactly on 10,000,000 cents earns the twenty percent band. The tier is keyed on the gross figure from step one and on nothing else — not on the post-fee net, and not on the declared total — which is what pins the evaluation order of an otherwise circular-looking pair, since the fee reduces the total while the total selects the fee's discount. Step three: multiply the ticket's `processing_fee_total_cents` by one minus the discount fraction and round the product half up to a whole number of cents, giving the final fee. Step four: the ticket's `final_settlement_cents` is the gross counted figure minus that final fee. Step five: the ticket's `settlement_delta_cents` is `final_settlement_cents` minus the ticket's `provisional_credit_cents` as it stands immediately before settlement unwinds it — a signed figure that is negative when the vault over-advanced against the declaration and positive when it under-advanced. No haircut and no cap apply on this side; for identical bag data the final figure lands on a different number than the provisional one did, and that gap is exactly what `settlement_delta_cents` records.

The ledger movements at settlement run in a fixed order. The depositor's `provisional_credit_cents` is reduced by the ticket's `provisional_credit_cents`, and the ticket's own `provisional_credit_cents` is then reset to 0 — the uncollected advance is retired. The depositor's `ledger_balance_cents` is increased by the ticket's `final_settlement_cents` — the funds are now collected. The depositor's `available_balance_cents` is recomputed as `ledger_balance_cents` plus `provisional_credit_cents`. Finally the persisted risk figures are refreshed by running the `SETTLED_ONLY` view of the risk model onto `risk_score` and `risk_grade`. A ticket that was held rather than credited settles the same way; its provisional amount is simply 0, so the first movement is a no-op and `settlement_delta_cents` equals `final_settlement_cents`.

The **risk model** scores a depositor out of 100 and comes in two views over the same arithmetic. Both begin by adding up `declared_total_cents` across the tickets in the view's input set, and by adding up the absolute value of `variance_cents` across every bag of every ticket in that input set whose counting axis reads `COUNTED` or `ADJUSTED` — absolute value, so a long bag is as damaging as a short one. If the declared total is 0 the variance ratio is taken as 0.00; otherwise the variance ratio is 100 multiplied by the absolute-variance total, divided by the declared total, and rounded half up to 2 decimal places. That rounding happens *before* the ratio is weighted, not after. The raw score then starts at 100 and subtracts three penalties: 1.5 points for each percentage point of variance ratio, 8 points for each counterfeit incident in the view, and 3 points for each denied claim on the account. The raw score is clamped into the range 0 through 100 inclusive — nothing below 0 and nothing above 100 — and then rounded half up to 2 decimal places to give the score. The letter band follows from the score: at least 80 is `A`, otherwise at least 60 is `B`, otherwise at least 40 is `C`, and anything below 40 is `D`.

The two views differ only in what they count. The `SETTLED_ONLY` view is the chronologically closed one and is the view that is ever persisted: its ticket input set is this depositor's tickets whose `status` is `SETTLED`, and its counterfeit count is the account's `counterfeit_incident_count`, which tallies `SUBMITTED` reports only. In-flight variance and unsent drafts are invisible to it. It is recomputed and written to `risk_score` and `risk_grade` whenever a ticket settles and whenever a counterfeit report enters or leaves `SUBMITTED`. The `POINT_IN_TIME` view is the forward-looking one and is never persisted anywhere: its ticket input set is this depositor's tickets whose `status` is any of `VERIFIED`, `PROVISIONAL_CREDITED`, `HELD`, `SETTLEMENT_READY` or `SETTLED` — everything from verification onward, but not tickets still in `INTAKE` — and its counterfeit count is the account's `counterfeit_incident_count` plus the number of `DRAFT` counterfeit reports whose fitness lots are reachable from this account's bags. The account's `denied_claim_count` is used unchanged by both views. Because the forward-looking view sees strictly more variance and strictly more counterfeit incidents, for identical stored data it yields a score no higher than the persisted one and can land in a different letter band.

Both views surface together on the **customer statement**, a read-only projection available to the depositor and to a `VaultManager`. It reports the account's `customer_account_id` alongside the persisted `ledger_balance_cents`, `provisional_credit_cents` and `available_balance_cents`, the persisted `risk_score` and `risk_grade` from the closed view, and the freshly computed `projected_risk_score` and `projected_risk_grade` from the forward-looking view. It also reports three tallies: `open_ticket_count`, the number of this depositor's deposit tickets not yet in `SETTLED`; `settled_ticket_count`, the number already in `SETTLED`; and `open_claim_count`, the number of this depositor's discrepancy claims currently in `SUBMITTED` or `INFO_REQUESTED`. Reading the statement persists nothing. Reading the account resource itself, by contrast, returns the stored balances and the stored `SETTLED_ONLY` grade without any projection.

### 3.8. Cash Letters to the Federal Reserve and Vault Reconciliation

Fit and unfit notes leave the vault in a **cash letter**. A `VaultManager` prepares one by naming the shipping `vault_id`, a `cash_letter_number` that must be unique across all cash letters — a collision is `ERR_DUPLICATE_IDENTIFIER` — a `deposit_date` giving the calendar date of the shipment in year-month-day form, and a `fitness_lot_ids` array naming the lots to bundle.

Eligibility for attachment is checked lot by lot. Every named lot must have a `category` of either `FIT` or `UNFIT` and a `status` of `PENDING_DEPOSIT`; a `COUNTERFEIT_SUSPECT` lot or one already attached, deposited or seized is `ERR_LOT_NOT_ELIGIBLE`. Every named lot must also have been counted on this vault's own floor — the counting machine behind the lot's counting session must belong to the same vault as the cash letter's `vault_id` — and a lot from another vault is `ERR_LOT_VAULT_MISMATCH`. If the array is empty, the failure is not a malformed-request error but `ERR_NO_ELIGIBLE_LOTS`; that is the one place where an empty array is treated as a business outcome rather than a shape violation.

A prepared cash letter is created in `PREPARED` with `declared_total_cents` frozen as the sum of `face_value_cents` over the lots named at creation, `attached_lot_count` frozen as the number of those lots, `credited_total_cents` and `adjustment_cents` at 0, and `submitted_at` and `confirmed_at` null. Each named lot has its `fed_deposit_id` set to the new cash letter and moves `PENDING_DEPOSIT → ATTACHED`. Because `declared_total_cents` is frozen at creation, nothing that happens to the lots afterwards changes it. Cash letters can be read individually, listed with optional `vault_id` and `status` filters, and their attached lots read back as a list filtered by `status`, all paged with `limit` and `offset`.

Shipping the cash letter moves it `PREPARED → SUBMITTED` and stamps `submitted_at` from the logical clock. Two guards apply beyond the state check. No counterfeit report may still be sitting in `DRAFT` on any fitness lot that shares a `count_session_id` with any lot attached to this cash letter — the compliance chain must be resolved before the vault ships anything counted alongside a suspect batch, and a pending draft is `ERR_COUNTERFEIT_REPORT_PENDING`. And the shipping vault must not be `FROZEN`, which yields `ERR_VAULT_FROZEN`. On success every attached lot moves `ATTACHED → DEPOSITED`.

The Federal Reserve responds through a `FederalReserveAgent`, who confirms the cash letter by reporting the `credited_total_cents` they actually credited. The adjustment is that reported figure minus the cash letter's frozen `declared_total_cents`, stored signed as `adjustment_cents`, and `confirmed_at` is stamped from the logical clock. The confirmation then branches on that adjustment. When the adjustment is exactly 0 — the Federal Reserve credited precisely what was declared — the cash letter moves `SUBMITTED → CONFIRMED` and no vault field moves at all. When the adjustment is anything other than 0, whether the Reserve credited above the declared figure or below it, the cash letter moves `SUBMITTED → CONFIRMED_WITH_ADJUSTMENT` and the shipping vault's `cash_letter_adjustment_cents` is increased by that signed adjustment. Only this second branch ever moves the vault's running adjustment total; the clean-confirmation branch leaves it untouched. Both branches are terminal.

A `VaultManager` can pull a **cash-letter reconciliation** for a vault at any time. It is a computed projection that persists nothing, and it reports five figures alongside the `vault_id`. The `shipped_total_cents` is the sum of `declared_total_cents` over this vault's cash letters whose `status` is `SUBMITTED`, `CONFIRMED` or `CONFIRMED_WITH_ADJUSTMENT`. The `credited_total_cents` is the sum of `credited_total_cents` over this vault's cash letters whose `status` is `CONFIRMED` or `CONFIRMED_WITH_ADJUSTMENT`. The `outstanding_cents` is the sum of `declared_total_cents` over this vault's cash letters whose `status` is `SUBMITTED` — value that has left the vault but has not yet been credited. The `net_adjustment_cents` is the sum of `adjustment_cents` over this vault's cash letters whose `status` is `CONFIRMED_WITH_ADJUSTMENT`. Cash letters still in `PREPARED` are excluded from every one of these totals, because nothing has physically left the vault yet. The boolean `reconciled` is true exactly when `outstanding_cents` is 0 **and** `net_adjustment_cents` equals the vault's own persisted `cash_letter_adjustment_cents`; if either condition fails, `reconciled` is false. All five figures are whole cents and no rounding occurs anywhere in this projection.

### 3.9. Coin Orders: Allocation, Release, and Return

The vault also sells change. A `CustomerAccountHolder` places a **coin order** by naming their own `customer_account_id`, the fulfilling `vault_id`, an inclusive `pickup_window_start` and an inclusive `pickup_window_end` for the armored pickup at the dock, and a non-empty `lines` array. Each entry in `lines` names a `denomination` — `PENNY`, `NICKEL`, `DIME` or `QUARTER` — and a `boxes_requested` count of at least 1. At most one line per denomination is permitted within a single order; naming the same denomination twice is `ERR_DUPLICATE_DENOMINATION`.

The dock has finite capacity. A vault's `pickup_concurrency_limit` is the number of live pickup windows that may cover any single instant. The requested window is treated as a **closed** interval, including both its start and its end instants, and if any instant inside it is already covered by that many or more of the vault's coin orders whose `status` is `REQUESTED`, `APPROVED_FULL` or `APPROVED_PARTIAL`, the order is refused with `ERR_PICKUP_CAPACITY_EXCEEDED`. Because the interval is closed at both ends, two windows that merely touch at a single instant do overlap for this purpose. Orders that have been rejected, released or returned no longer occupy the dock and do not count toward the limit.

A placed order is created in `REQUESTED` with one **order line** per entry in `lines`, each recording its `coin_order_id`, `denomination` and `boxes_requested`, with `boxes_allocated`, `boxes_returned` and `line_face_value_cents` all at 0. The order's `total_boxes_requested` is computed as the sum of `boxes_requested` across its lines; `total_boxes_allocated`, `fill_ratio_pct` and `charge_cents` are 0, and `approved_by_user_id`, `released_by_user_id` and `return_reason` are null. Orders can be read singly, listed with optional `customer_account_id`, `vault_id` and `status` filters, and their lines read back as a list; all of these accept `limit` and `offset`.

Approval is a `VaultManager` decision carrying a single boolean input, `allow_partial`, and it requires the depositor's account `status` to be `ACTIVE`, with a suspended account yielding `ERR_ACCOUNT_SUSPENDED`. The **allocation** then runs line by line, and the order in which lines are processed is fixed: ascending coin value, so the penny line is allocated first, then nickels, then dimes, then quarters. Since at most one line per denomination exists, that sort key is total and no tie-break is ever reachable. For each line in turn, the system looks up the vault's inventory position for that denomination. If no position row exists for that pair, the available figure is 0 and the line simply allocates nothing — this is not an error. Otherwise the available figure is `on_hand_boxes` minus `reserved_boxes`, floored at 0. The line's `boxes_allocated` is the smaller of its `boxes_requested` and that available figure, and its `line_face_value_cents` is `boxes_allocated` multiplied by the face value of a standard box of that denomination — 2,500 cents for pennies, 10,000 cents for nickels, 25,000 cents for dimes and 50,000 cents for quarters. The position's `reserved_boxes` is then increased by the boxes just allocated, and `available_boxes` is recomputed as `on_hand_boxes` minus `reserved_boxes` floored at 0, before the next line is considered — allocation is strictly sequential and each line's reservation is visible to the line that follows it in the same run.

Once every line has been walked, the order's `total_boxes_allocated` is the sum of `boxes_allocated` across its lines, its `charge_cents` is the sum of `line_face_value_cents` across its lines, and its `fill_ratio_pct` is 100 multiplied by `total_boxes_allocated`, divided by `total_boxes_requested`, rounded half up to 2 decimal places. Three outcomes follow, and only the vault's inventory decides which. If `total_boxes_allocated` is 0, nothing could be filled at all: the order moves `REQUESTED → REJECTED`, `fill_ratio_pct` is 0 and `charge_cents` is 0, and no inventory position is touched. A zero allocation is a business outcome, not an error, and this holds regardless of what `allow_partial` said. If `fill_ratio_pct` is exactly 100.00, every requested box was reserved and the order moves `REQUESTED → APPROVED_FULL`. If the fill is somewhere strictly between 0 and 100 percent, the order moves `REQUESTED → APPROVED_PARTIAL` when `allow_partial` was true; when `allow_partial` was false the partial fill is refused with `ERR_INSUFFICIENT_COIN_INVENTORY` and nothing is reserved. On any of the three successful outcomes the acting `X-User-ID` is recorded as `approved_by_user_id` and the vault's `version` is incremented by 1.

Release hands the boxes to the carrier and is a `VaultTeller` operation, legal from either `APPROVED_FULL` or `APPROVED_PARTIAL`. It carries `expected_vault_version`, which must match the vault's current `version` as described in §2.8, and it is guarded three further ways. The releasing teller's `X-User-ID` must differ from the order's `approved_by_user_id`, or the release is `ERR_DUAL_CONTROL_VIOLATION`. The vault's `posture` must be `OPEN`: a `RESTRICTED` posture yields `ERR_VAULT_RESTRICTED` and a `FROZEN` posture yields `ERR_VAULT_FROZEN`. And for every line, the vault's inventory position for that denomination must have `on_hand_boxes` of at least the line's `boxes_allocated`; if a shrinkage write-down has eaten into the physical position since approval, the release fails with `ERR_INSUFFICIENT_COIN_INVENTORY`.

A successful release moves the order `APPROVED_FULL → RELEASED` or `APPROVED_PARTIAL → RELEASED`, depending on which approved state it was in, and does five things. Per denomination, the position's `on_hand_boxes` and `reserved_boxes` are each decreased by that line's `boxes_allocated`, with `available_boxes` recomputed as `on_hand_boxes` minus `reserved_boxes` floored at 0. The vault's `coin_face_value_on_hand_cents` is recomputed from the new positions. The depositor's `ledger_balance_cents` is decreased by the order's `charge_cents` and `available_balance_cents` is recomputed as `ledger_balance_cents` plus `provisional_credit_cents`. The acting `X-User-ID` is recorded as `released_by_user_id`. And the vault's `version` is incremented by 1, which is what makes a second release attempt against the same observed version fail.

An entire released order can be taken back. Returning it is a `VaultTeller` operation from `RELEASED` only, requires a `return_reason` which is recorded, and moves the order `RELEASED → RETURNED`, which is terminal. Every line's `boxes_returned` is set equal to its `boxes_allocated` — returns are all-or-nothing, never partial. Per denomination the position's `on_hand_boxes` is increased by that line's `boxes_allocated` while `reserved_boxes` is deliberately left untouched, since the reservation was already consumed at release; `available_boxes` is recomputed and the vault's `coin_face_value_on_hand_cents` is recomputed. The depositor's `ledger_balance_cents` is increased by the order's `charge_cents` and `available_balance_cents` is recomputed. The vault's `version` is incremented by 1. Taken together, a release followed by a return leaves the vault's coin face value and the customer's ledger balance exactly where they stood before the release.

## 4. Endpoint Definitions

Every endpoint in this API is mounted under `/cash-vault`. Creating a brand-new resource returns HTTP 201; every other successful call — reads, lifecycle transitions, allocations, adjustments and projections — returns HTTP 200. Successful mutations return the affected resource in the envelope's `data` field. The table below is a routing summary only: the request payload, the response payload and the side effects of each operation are specified in the §3 narratives, and the validation ordering that governs which error surfaces first is specified in §2.6.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/cash-vault/_clock/set_current_utc` | Set the server's logical clock. | `VaultManager` |
| POST | `/cash-vault/vaults` | Register a processing-center vault. | `VaultManager` |
| GET | `/cash-vault/vaults/{id}` | Read one vault, including its current posture and version. | `VaultManager`, `VaultTeller`, `ComplianceOfficer`, `FederalReserveAgent` |
| POST | `/cash-vault/vaults/{id}/posture` | Move the vault posture between OPEN, RESTRICTED and FROZEN. | `VaultManager` |
| POST | `/cash-vault/vaults/{id}/inventory-adjustments` | Apply a signed box delta to one coin denomination's inventory position, creating the VaultInventory row on first use. | `VaultManager` |
| GET | `/cash-vault/vaults/{id}/inventory` | List the coin inventory positions held by this vault. | `VaultManager`, `VaultTeller` |
| GET | `/cash-vault/vaults/{id}/cash-letter-reconciliation` | Computed reconciliation of this vault's Federal Reserve cash letters against confirmed credits. | `VaultManager` |
| POST | `/cash-vault/customer-accounts` | Open a depositor account. | `VaultManager` |
| GET | `/cash-vault/customer-accounts/{id}` | Read one depositor account with its persisted balances and SETTLED_ONLY risk grade. | `VaultManager`, `VaultTeller`, `CustomerAccountHolder` |
| GET | `/cash-vault/customer-accounts/{id}/statement` | Customer statement: persisted balances plus the POINT_IN_TIME variant of customer_risk_grade, which is computed on read and never stored. | `VaultManager`, `CustomerAccountHolder` |
| POST | `/cash-vault/deposit-tickets` | Open an intake ticket for an armored drop. | `ArmoredCarrier` |
| GET | `/cash-vault/deposit-tickets/{id}` | Read one deposit ticket. | `VaultManager`, `VaultTeller`, `ArmoredCarrier`, `CustomerAccountHolder` |
| GET | `/cash-vault/deposit-tickets` | List deposit tickets, filterable by depositor, vault and lifecycle state. | `VaultManager`, `VaultTeller`, `CustomerAccountHolder` |
| POST | `/cash-vault/deposit-tickets/{id}/verify` | Verify the drop: bag count matches the manifest and every bag is physically in the vault. | `VaultTeller` |
| POST | `/cash-vault/deposit-tickets/{id}/provisional-credit` | Extend provisional (uncollected) credit using deposit_credit_amount variant PROVISIONAL. | `VaultTeller` |
| POST | `/cash-vault/deposit-tickets/{id}/reverse-provisional-credit` | Withdraw provisional credit already extended on this ticket. | `VaultManager` |
| POST | `/cash-vault/deposit-tickets/{id}/hold` | Hold the drop instead of extending credit. | `VaultManager` |
| POST | `/cash-vault/deposit-tickets/{id}/settle` | Settle the ticket using deposit_credit_amount variant FINAL and reconcile the provisional credit. | `VaultManager` |
| POST | `/cash-vault/sealed-bags` | Register a sealed bag against an intake ticket. | `ArmoredCarrier` |
| GET | `/cash-vault/sealed-bags/{id}` | Read one sealed bag, including both state axes and its version. | `VaultManager`, `VaultTeller`, `ArmoredCarrier`, `CustomerAccountHolder` |
| GET | `/cash-vault/sealed-bags` | List sealed bags, filterable by ticket and by either state axis. | `VaultManager`, `VaultTeller` |
| POST | `/cash-vault/sealed-bags/{id}/custody-events` | Append one chain-of-custody hop, advancing SealedBag.custody_status. | `ArmoredCarrier`, `VaultTeller` |
| GET | `/cash-vault/sealed-bags/{id}/custody-events` | Read the ordered chain of custody for a bag. | `VaultManager`, `VaultTeller`, `ArmoredCarrier` |
| POST | `/cash-vault/counting-machines` | Commission a sorter or counter on a vault floor. | `VaultManager` |
| GET | `/cash-vault/counting-machines/{id}` | Read one counting machine. | `VaultManager`, `VaultTeller` |
| GET | `/cash-vault/counting-machines` | List counting machines, filterable by vault and availability. | `VaultManager`, `VaultTeller` |
| POST | `/cash-vault/count-sessions` | Schedule a counting window for one bag on one machine. | `VaultTeller` |
| GET | `/cash-vault/count-sessions/{id}` | Read one count session. | `VaultManager`, `VaultTeller` |
| GET | `/cash-vault/count-sessions` | List count sessions, filterable by bag, machine and state. | `VaultManager`, `VaultTeller` |
| POST | `/cash-vault/count-sessions/{id}/start` | Open the bag on the machine and begin counting. | `VaultTeller` |
| POST | `/cash-vault/count-sessions/{id}/complete` | Report machine totals and the fitness-sorted lot breakdown. | `VaultTeller` |
| GET | `/cash-vault/count-sessions/{id}/fitness-lots` | Read the fitness-sorted lots produced by a session. | `VaultManager`, `VaultTeller`, `ComplianceOfficer` |
| POST | `/cash-vault/counterfeit-reports` | Draft a counterfeit report against a COUNTERFEIT_SUSPECT lot. | `ComplianceOfficer` |
| GET | `/cash-vault/counterfeit-reports/{id}` | Read one counterfeit report. | `ComplianceOfficer`, `VaultManager` |
| GET | `/cash-vault/counterfeit-reports` | List counterfeit reports, filterable by lot and state. | `ComplianceOfficer`, `VaultManager` |
| POST | `/cash-vault/counterfeit-reports/{id}/submit` | Submit the report; seizes the lot and propagates the loss up the bag and ticket. | `ComplianceOfficer` |
| POST | `/cash-vault/counterfeit-reports/{id}/return-for-correction` | Return a submitted report to DRAFT and unwind every seizure side effect. | `ComplianceOfficer` |
| POST | `/cash-vault/counterfeit-reports/{id}/acknowledge` | Record the Secret Service case number and close the report. | `ComplianceOfficer` |
| POST | `/cash-vault/discrepancy-claims` | File a discrepancy claim or a statement-adjustment dispute inside the claim window. | `CustomerAccountHolder` |
| GET | `/cash-vault/discrepancy-claims/{id}` | Read one claim. | `VaultManager`, `CustomerAccountHolder` |
| GET | `/cash-vault/discrepancy-claims` | List claims, filterable by bag, depositor and state. | `VaultManager`, `CustomerAccountHolder` |
| POST | `/cash-vault/discrepancy-claims/{id}/request-info` | Return the claim to the customer for more information. | `VaultManager` |
| POST | `/cash-vault/discrepancy-claims/{id}/resubmit` | Resubmit the claim with a revised amount, closing one review round. | `CustomerAccountHolder` |
| POST | `/cash-vault/discrepancy-claims/{id}/approve` | Approve the claim, adjust the bag and release the settlement block. | `VaultManager` |
| POST | `/cash-vault/discrepancy-claims/{id}/deny` | Deny the claim; the settlement block is released without moving money. | `VaultManager` |
| POST | `/cash-vault/fed-deposits` | Prepare a Federal Reserve cash letter over eligible fitness lots. | `VaultManager` |
| GET | `/cash-vault/fed-deposits/{id}` | Read one cash letter. | `VaultManager`, `FederalReserveAgent` |
| GET | `/cash-vault/fed-deposits` | List cash letters, filterable by vault and state. | `VaultManager`, `FederalReserveAgent` |
| POST | `/cash-vault/fed-deposits/{id}/submit` | Ship the cash letter to the Federal Reserve. | `VaultManager` |
| POST | `/cash-vault/fed-deposits/{id}/confirm` | Record the Federal Reserve's credit advice and any cash-letter adjustment. | `FederalReserveAgent` |
| GET | `/cash-vault/fed-deposits/{id}/fitness-lots` | Read the lots attached to a cash letter. | `VaultManager`, `FederalReserveAgent` |
| POST | `/cash-vault/coin-orders` | Place a coin/change order with a CLOSED armored pickup window at the vault. | `CustomerAccountHolder` |
| GET | `/cash-vault/coin-orders/{id}` | Read one coin order. | `VaultManager`, `VaultTeller`, `CustomerAccountHolder` |
| GET | `/cash-vault/coin-orders` | List coin orders, filterable by depositor, vault and state. | `VaultManager`, `VaultTeller`, `CustomerAccountHolder` |
| POST | `/cash-vault/coin-orders/{id}/approve` | Run coin_order_allocation and reserve inventory. | `VaultManager` |
| POST | `/cash-vault/coin-orders/{id}/release` | Hand the coin to the carrier at pickup, moving boxes out of the vault and debiting the account. | `VaultTeller` |
| POST | `/cash-vault/coin-orders/{id}/return` | Take back an entire released order. | `VaultTeller` |
| GET | `/cash-vault/coin-orders/{id}/lines` | Read the per-denomination lines of a coin order, including allocations and returns. | `VaultManager`, `VaultTeller`, `CustomerAccountHolder` |

## 5. Error Code Catalogue

The table below lists every error identifier this API can return together with its HTTP status code. The conditions that trigger each one are described where the corresponding rule lives — in the global principles of §2 and in the workflow narratives of §3 — and the relative order in which competing conditions are evaluated is given in §2.6.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_ACCOUNT_OWNERSHIP` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_VAULT_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_BAG_NOT_FOUND` | 404 |
| `ERR_MACHINE_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_FED_DEPOSIT_NOT_FOUND` | 404 |
| `ERR_COIN_ORDER_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BAG_NOT_RECEIVED` | 409 |
| `ERR_BAG_COUNT_MISMATCH` | 409 |
| `ERR_BAG_NOT_COUNTED` | 409 |
| `ERR_VAULT_FROZEN` | 409 |
| `ERR_VAULT_RESTRICTED` | 409 |
| `ERR_MACHINE_UNAVAILABLE` | 409 |
| `ERR_DUAL_CONTROL_VIOLATION` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_COUNTERFEIT_REPORT_PENDING` | 409 |
| `ERR_MACHINE_TYPE_MISMATCH` | 422 |
| `ERR_REPORT_LOT_MISMATCH` | 422 |
| `ERR_LOT_NOT_ELIGIBLE` | 422 |
| `ERR_LOT_VAULT_MISMATCH` | 422 |
| `ERR_MACHINE_WINDOW_CONFLICT` | 409 |
| `ERR_WINDOW_IN_PAST` | 422 |
| `ERR_PICKUP_CAPACITY_EXCEEDED` | 409 |
| `ERR_DUPLICATE_DENOMINATION` | 422 |
| `ERR_CLAIM_WINDOW_CLOSED` | 422 |
| `ERR_CLAIM_ROUND_LIMIT` | 409 |
| `ERR_DUPLICATE_SEAL` | 409 |
| `ERR_DUPLICATE_IDENTIFIER` | 409 |
| `ERR_SEAL_TAMPERED` | 409 |
| `ERR_NO_ELIGIBLE_LOTS` | 422 |
| `ERR_LOT_TOTAL_MISMATCH` | 422 |
| `ERR_MATERIAL_VARIANCE_UNRESOLVED` | 409 |
| `ERR_ACCOUNT_SUSPENDED` | 409 |
| `ERR_INSUFFICIENT_COIN_INVENTORY` | 409 |
| `ERR_INVENTORY_NEGATIVE` | 422 |
| `ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED` | 422 |
| `ERR_RESOLUTION_EXCEEDS_CLAIM` | 422 |
