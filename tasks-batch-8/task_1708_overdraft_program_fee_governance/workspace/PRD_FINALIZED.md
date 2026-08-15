# Overdraft Fee Governance API — Product Requirements Document

## 1. Introduction

Retail deposit programs live or die by how defensibly they handle overdrafts. Regulators expect opt-in consent for one-time debit coverage to be documented against a specific disclosure version, fee assessment to follow a declared posting order, daily fee exposure to be capped, sustained negative balances to follow a published restriction and charge-off timeline, and fee waivers to respect segregation-of-duties authority limits. This document specifies the Overdraft Fee Governance API: a service that lets a bank configure an overdraft program, run the daily posting-batch lifecycle that applies that program to account transactions, govern fee waivers through tiered approval bands, communicate program changes through timed disclosure notices, steer heavy-fee customers toward alternative products, and produce the revenue and scrutiny metrics that compliance teams must file.

All API paths described in this document are mounted under the `/v1` prefix. Time inside the service is logical rather than wall-clock, and every rule below — fee assessment, notice windows, offer expiry, reporting periods — is evaluated against that logical clock, which makes every workflow in this document fully reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes seven distinct roles: `ProgramAdmin`, `OperationsClerk`, `Teller`, `Supervisor`, `Manager`, `ComplianceOfficer`, and `AccountHolder`. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Access to every operation is restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

For six of the seven roles, the identity header is not tied to any persisted entity. When `X-User-Role` is `ProgramAdmin`, `OperationsClerk`, `Teller`, `Supervisor`, `Manager`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier: the server may record it (for example, as `created_by_user_id` on a waiver request or `finalized_by_user_id` on a regulatory report, where a workflow writes it) but never compares it to any entity's `id`. When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `DepositAccount`; ownership checks on any resource that references a `DepositAccount` compare the resource's account reference to `X-User-ID`, and a mismatch is rejected with `ERR_ACCOUNT_OWNERSHIP_MISMATCH`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Business Dates

The server runs on a logical clock that never falls back to wall-clock time. At startup the clock reads exactly 2026-08-01T00:00:00Z. A `ProgramAdmin` may advance or set the clock through a test-driving capability that accepts a target instant in the `to_iso8601` field and echoes the new value back as `current_utc`. Every system-generated timestamp — `elected_at`, `last_changed_at`, `sent_at`, `effective_at`, `expires_at` — and every system-generated business date — `authorized_date`, `posted_date` — derives from this logical clock. Setting the clock has one standing side effect: any lazily-expiring education offer is re-evaluated on subsequent reads and actions, so an offer whose expiry has passed will surface as expired the next time it is observed or acted upon.

Business dates are calendar dates in `YYYY-MM-DD` form, and a posting batch may only be opened for a Monday-through-Friday date. A batch creation naming a Saturday or Sunday date is rejected with `ERR_NON_BUSINESS_DAY` (HTTP 422).

### 2.5. Common Resource Properties

All primary resources in the system — programs, accounts, opt-in elections, transactions, batches, fees, waiver requests, change notices, education offers, and regulatory reports — carry a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** An ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- **`version` (integer):** A system-managed integer that increments by one on every mutation of the resource and serves as the basis for optimistic concurrency control.

The three-fractional-digit form is not special to `created_at`: every system-generated timestamp string the API serves — including `updated_at`, the clock-derived instants of §2.4 (`elected_at`, `last_changed_at`, `sent_at`, `effective_at`, `expires_at`), and the clock endpoint's `current_utc` echo — is rendered as an ISO 8601 UTC timestamp with exactly three fractional digits, so a whole-second instant carries a `.000` fraction (for example, `2026-08-01T00:00:00.000Z`).

The single exception is the waiver request item — the per-fee allocation row of a waiver request — which is immutable after creation and therefore carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Money, Counts, and Rounding Discipline

All monetary values are represented as integer cents; no floating-point arithmetic appears anywhere in the system, and fee assessment itself is exact integer arithmetic with no rounding. Two calculations do involve division, and each has a pinned rounding rule. Percentage-based waiver allocations round **half up per fee item** before the per-item amounts are summed — rounding the sum instead of the items can differ by a cent and is forbidden. Regulatory ratios (a basis-point waiver ratio and a per-overdrafter average expressed in hundredths of a fee) use floor division: any fractional remainder is discarded. Calendar counts — day thresholds, window lengths, expiry periods — are integers with at-least semantics at their thresholds unless a rule explicitly says otherwise.

### 2.7. Working Balance versus Ledger Balance

Two distinct balances exist while a posting batch is being sealed, and confusing them breaks the entire fee model. The **working balance** starts from the account's persisted `ledger_balance_cents` and moves as each item posts — credits raise it, paid debits lower it — but it never includes fees. The **ledger balance** is what is written back to the account when the seal completes: it equals the final working balance, because fees assessed during the seal are not debited until the batch later settles. The evaluation order per item is pinned to break the circularity this could otherwise create: first the projected balance is computed from the working balance and the item amount; second, the pay-or-return decision uses that projection alone; third, the de minimis and daily-cap checks evaluate the working balance *after* the item posts; and fourth, any fee created by those checks does not modify the working balance, so it cannot influence the pay/return decision, the de minimis test, or the cap test of any later item in the same batch. The practical consequence is that same-batch fees never cascade into extra returns or extra fees.

### 2.8. Optimistic Concurrency Control

Exactly two write operations in the API carry an optimistic-concurrency check, each keyed to the version of a parent entity. Creating a program-change notice requires the request to carry `expected_program_version`, holding the `version` of the target program as the client last observed it; if the program's current `version` no longer matches — because another writer has since created a notice (legitimately superseding a draft on the same parameter) or a notice activation has repriced the program — the creation is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412), preventing the client from acting on a program definition it has not observed. Creating an education offer requires `expected_account_version` carrying the account's last-observed `version`; a mismatch is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412), which matters because creation legitimately supersedes any currently offered offer, and a stale view means the writer may be superseding an offer it never saw. Endpoints other than these two do not take a version field at all.

### 2.9. Segregation of Duties

Three workflows deliberately split authority across people. A fee waiver request records `created_by_user_id` and `created_by_role` at submission, and no subsequent approval or denial may be performed by the same user: an approver or denier whose `X-User-ID` equals the request's `created_by_user_id` is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`. A regulatory report records `finalized_by_user_id` at finalization, and the submitter must be a different compliance officer — submission by the finalizer is rejected with `ERR_SELF_SUBMISSION_FORBIDDEN`. Program-change notices split issuance from activation by role: a `ProgramAdmin` drafts and issues a notice, but only a `ComplianceOfficer` may activate it once its disclosure window has elapsed.

### 2.10. Validation Precedence and Identifier Resolution

Validation on any request executes in a fixed precedence order, and a failure at an earlier tier masks every later check. The tiers, in order: first, the presence and non-emptiness of the identity headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, whether the caller's role is authorized for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`); third, body well-formedness — required fields present, enum values valid, amounts positive, date strings parseable, and kind-specific fields supplied (`ERR_INVALID_REQUEST`); fourth, existence of every referenced identifier (`ERR_NOT_FOUND`); fifth, holder ownership for `AccountHolder` callers (`ERR_ACCOUNT_OWNERSHIP_MISMATCH`); sixth, account status gates (`ERR_ACCOUNT_RESTRICTED`, `ERR_ACCOUNT_CLOSED`); seventh, state-machine validity of the requested transition and waivability of listed fees (`ERR_INVALID_STATE_TRANSITION`, `ERR_FEE_NOT_WAIVABLE`); eighth, program posture and disclosure compliance (`ERR_PROGRAM_SUSPENDED`, `ERR_STALE_DISCLOSURE_VERSION`); ninth, the time-window rules covering notice windows, report periods, business days, settle ordering, reversal windows, and offer expiry; tenth, uniqueness and segregation constraints; eleventh, close economics; twelfth, money rules covering waiver authority, waiver amount validity, and recovery caps; and thirteenth, last, optimistic-concurrency staleness. Because staleness is checked last, a request failing any earlier tier never surfaces a stale-version error.

Existence checking within the fourth tier resolves identifiers from left to right. When an endpoint path contains a resource identifier, that identifier is validated first; body-referenced identifiers such as `program_id`, `account_id`, and each entry of `fee_ids` are validated against the datastore in the same pass, and the first identifier that does not correspond to an existing resource yields `ERR_NOT_FOUND` (HTTP 404). Operations therefore never proceed in a context whose container does not exist.

## 3. Business Logic & Workflows

### 3.1. Program Configuration and Governance Posture

Everything in the system is governed by an **OverdraftProgram**, which a `ProgramAdmin` creates with a display `name` and thirteen policy parameters. The fee schedule is set by `fee_amount_cents` — the per-item overdraft fee, which must be greater than zero — together with two independent daily brakes: `daily_fee_cap_cents`, the maximum total overdraft fee cents one account may be assessed within a single business-date batch, and `max_daily_fees_count`, the maximum number of `OVERDRAFT` fees one account may be assessed within that batch. The `de_minimis_threshold_cents` parameter suppresses fees for trivially negative balances. The sustained-overdraft timeline is governed by `sustained_overdraft_days_threshold`, the count of consecutive settled business days with a negative ledger that triggers account restriction; `sustained_overdraft_fee_cents`, a one-time fee assessed when restriction first takes hold, which is exempt from the daily caps; and `charge_off_grace_business_days`, the number of settled business days an account may sit restricted and negative before it is charged off. Disclosure governance uses `notice_window_days`, the calendar days that must elapse between a change notice being issued and its earliest activation, and `current_disclosure_version`, the disclosure text version that opt-in elections must reference. Customer steering is tuned by `steering_fee_count_threshold` and `steering_window_days` — the fee count within a trailing window that triggers an automatic education offer — plus `offer_expiry_days`, how long an offer remains open. Finally, `posting_order_policy` selects how debits are ordered inside a batch seal: `HIGH_TO_LOW` or `CHRONOLOGICAL`. A new program is born `ACTIVE` with `version` equal to 1.

A `ProgramAdmin` may suspend a program, moving its `status` from `ACTIVE` to `SUSPENDED`, and later resume it, returning from `SUSPENDED` to `ACTIVE`; both transitions increment the program's `version`. Suspension is a governance brake, not a halt: while `SUSPENDED`, the program refuses new account openings and notice activations (each rejected with `ERR_PROGRAM_SUSPENDED`), no `OVERDRAFT` fees are assessed during a batch seal even though items still post normally — including debits paid into overdraft and NSF returns — and the one-time sustained fee is skipped at settle time. Day counting, restriction, cure, and charge-off transitions continue to run against a suspended program.

### 3.2. Accounts, Consent, and Opt-In Elections

A `Teller` or `ProgramAdmin` opens a **DepositAccount** by supplying the `program_id` of the governing program and the customer's `holder_name`; opening under a `SUSPENDED` program is rejected with `ERR_PROGRAM_SUSPENDED`. The account begins `ACTIVE` with `ledger_balance_cents` at zero and every counter at zero. Beyond its `status`, an account carries a running set of derived aggregates: `consecutive_negative_business_days` counts settled batches after which the ledger stayed negative and resets to zero on any settle where the ledger is non-negative; `restricted_business_days` counts settled business days elapsed since the account entered `RESTRICTED` while still negative; `lifetime_fees_assessed_cents` accumulates the `amount_cents` of every fee ever assessed against the account, whether an `OVERDRAFT` fee created at seal or a `SUSTAINED` fee created at settle; and `lifetime_fees_waived_cents` accumulates waived cents applied by approved waiver requests or by system voids. After a charge-off, three more fields tell the recovery story: `charge_off_original_cents` records the principal at closure, `charged_off_cents` tracks the still-unrecovered remainder, and `recovered_cents` accumulates recovery credits — with the invariant that `charged_off_cents` plus `recovered_cents` always equals `charge_off_original_cents`. The account collection can be listed with optional `program_id` and `status` filters.

Consent for one-time debit coverage lives on the **OptInElection**. An account has at most one election, ever — a second creation attempt is rejected with `ERR_ELECTION_ALREADY_EXISTS` — and an account with no election at all is simply not opted in. An `AccountHolder` (for their own account) or a `Teller` creates the election with a `channel` of `BRANCH`, `ONLINE`, `PHONE`, or `MAIL` documenting how consent was captured, and a `disclosure_version` that must exactly equal the program's `current_disclosure_version` at that moment; a stale or mismatched version is rejected with `ERR_STALE_DISCLOSURE_VERSION`. The election is born `OPTED_IN` with `elected_at` stamped from the logical clock. Elections can be listed with an optional `account_id` filter, which returns an array of zero or one element given the one-per-account rule.

The election is cyclic and may flip without bound. Revoking moves `OPTED_IN` to `REVOKED` and refreshes `last_changed_at` from the clock; it is permitted from any account posture except a closed one — revoking against a `CLOSED_VOLUNTARY` or `CLOSED_CHARGEOFF` account is rejected with `ERR_ACCOUNT_CLOSED`. Reinstating moves `REVOKED` back to `OPTED_IN` under tighter conditions: the owning account must be `ACTIVE` (a `RESTRICTED` account blocks reinstatement with `ERR_ACCOUNT_RESTRICTED`, and a closed one with `ERR_ACCOUNT_CLOSED`), and the payload's `disclosure_version` must again equal the program's `current_disclosure_version`, else `ERR_STALE_DISCLOSURE_VERSION`. A successful reinstatement also refreshes `last_changed_at`.

Voluntary closure is available to a `Teller` or `ProgramAdmin`, but only for an `ACTIVE` account — attempting it from any other status is an invalid state transition — and only when the account's economics are clean. Closing with a negative `ledger_balance_cents` is rejected with `ERR_CLOSE_NEGATIVE_BALANCE`. Closing with open items — any fee still `ASSESSED`, any waiver request in `PENDING_SUPERVISOR`, `PENDING_MANAGER`, or `PENDING_COMPLIANCE`, or any education offer still `OFFERED` — is rejected with `ERR_OPEN_ITEMS_BLOCK_CLOSE`. A clean close moves the account to `CLOSED_VOLUNTARY` and increments its `version`.

### 3.3. Authorizing Transactions and the Recovery Exception

Frontline activity enters the system as **AccountTransaction** authorizations. An `AccountHolder` (against their own account) or a `Teller` authorizes a transaction by supplying `account_id`, a `type` of `DEBIT_ONE_TIME`, `DEBIT_RECURRING`, `DEBIT_ACH`, `DEBIT_CHECK`, or `CREDIT_DEPOSIT`, and an `amount_cents` greater than zero. The authorization is born `AUTHORIZED`, with `authorized_date` stamped as the calendar date of the logical clock; its `batch_id`, `posting_sequence`, and `posted_date` stay null until a batch claims it. Transactions can be listed with optional `account_id`, `batch_id`, `status`, and `type` filters.

Account posture gates authorization. On a `RESTRICTED` account, new debit authorizations are rejected with `ERR_ACCOUNT_RESTRICTED`, though credits remain welcome. On a `CLOSED_VOLUNTARY` account every mutation is rejected with `ERR_ACCOUNT_CLOSED`. A `CLOSED_CHARGEOFF` account admits exactly one operation: a `CREDIT_DEPOSIT`, which serves as a charge-off recovery. A recovery credit never enters a batch — it posts immediately, born `POSTED` with `batch_id` and `posting_sequence` left null and `posted_date` set to the creation date — and its amount may not exceed the account's remaining `charged_off_cents`, else the attempt is rejected with `ERR_RECOVERY_EXCEEDS_CHARGEOFF` (HTTP 422). Each posted recovery increases `recovered_cents` and decreases `charged_off_cents` by the same amount, preserving the charge-off invariant; the account's `ledger_balance_cents`, zeroed at charge-off, is not altered by recovery postings.

### 3.4. Sealing the Daily Batch: Posting Order, Fee Assessment, and Reversal

The daily ledger run begins when an `OperationsClerk` opens a **PostingBatch** for a program by supplying `program_id` and a `business_date`. The date must be a Monday-through-Friday business day — weekend dates fail with `ERR_NON_BUSINESS_DAY` — and at most one non-`CANCELLED` batch may exist per program per business date: a duplicate is rejected with `ERR_BATCH_ALREADY_EXISTS`, though a `CANCELLED` batch frees its date for reuse. A new batch is `OPEN` with all four counters — `items_posted_count`, `items_returned_count`, `fees_assessed_count`, `fees_assessed_cents` — at zero. Batches can be listed with optional `program_id`, `business_date`, and `status` filters. An `OPEN` batch that has not yet had any transaction assigned to it may be cancelled outright, moving it to `CANCELLED`; once a seal has consumed the batch, cancellation is no longer a valid transition.

Sealing is the heart of the system. When the clerk seals an `OPEN` batch — sealing from any other status is rejected with `ERR_INVALID_STATE_TRANSITION` — the server sweeps every transaction still `AUTHORIZED` whose `authorized_date` falls on or before the batch's `business_date` and whose account belongs to the batch's program; already-`POSTED`, `RETURNED_NSF`, or `REVERSED` items are never touched. Accounts are processed one at a time in order of account `created_at`, earliest first, and within each account the working-balance discipline of §2.7 applies. Items are ordered deterministically: all `CREDIT_DEPOSIT` items post first, ordered by `authorized_date` earliest first with ties broken by earlier `created_at`; then debits post according to the program's `posting_order_policy` — under `HIGH_TO_LOW`, largest `amount_cents` first with ties broken by earlier `authorized_date` and then earlier `created_at`, while under `CHRONOLOGICAL`, debits post by earlier `authorized_date` with ties broken by earlier `created_at`. Ties are never broken by identifier. Each swept item receives a per-account, one-based `posting_sequence`, along with its `batch_id` and a `posted_date` equal to the batch's business date. The posting-order choice is not cosmetic: an identical input set can yield more fees under `HIGH_TO_LOW`, because large debits push the balance negative earlier, whereas `CHRONOLOGICAL` lets a starting balance absorb small items first and can yield fewer fees.

Each item then faces the pay-or-return decision. A credit simply raises the working balance and posts. For a debit, the projected balance — working balance minus the item amount — is computed first; if the projection is not negative, the item posts and processing continues. If the projection is negative, the item is payable unless it is a `DEBIT_ONE_TIME` and the account has no `OPTED_IN` election; a non-payable one-time debit is moved to `RETURNED_NSF` with its `batch_id`, `posting_sequence`, and `posted_date` assigned, the balance left unchanged, and no fee of any kind created. Recurring debits, ACH debits, and checks are always payable into overdraft regardless of election status, as is any one-time debit while the account's election stands `OPTED_IN`.

A paid-into-overdraft debit then faces the four-part fee test, evaluated against the working balance *after* the item posts. An `OVERDRAFT` fee is assessed only when all four hold: the program is `ACTIVE`; the magnitude of the now-negative working balance is strictly greater than `de_minimis_threshold_cents` — a balance exactly at the threshold yields no fee; the count of overdraft fees already assessed for this account in this batch is strictly below `max_daily_fees_count` — being already at the count cap blocks the fee; and the fee cents assessed so far plus `fee_amount_cents` does not exceed `daily_fee_cap_cents` — an exact fit that lands precisely on the cap is permitted. When the test passes, the system creates an **OverdraftFee** of `fee_type` `OVERDRAFT` in `ASSESSED` status with `amount_cents` equal to the program's `fee_amount_cents`, linked to the account, the batch, and the originating transaction via `account_id`, `batch_id`, and `transaction_id`; `waived_cents` starts at zero, `outstanding_cents` is the amount minus the waived portion, and `posted_date` remains null until settle. The account's `lifetime_fees_assessed_cents` grows by the fee amount, and the batch's `fees_assessed_count` and `fees_assessed_cents` counters accumulate alongside `items_posted_count` and `items_returned_count`. When the sweep finishes, each touched account's `ledger_balance_cents` is set to its final working balance — fees still undebted — and its `version` increments. The fee ledger can be queried with optional `account_id`, `batch_id`, `transaction_id` (a filter returning an array of zero or one element), `status`, and `fee_type` filters.

Between seal and settle there is a correction window. While a transaction's batch remains `SEALED`, an `OperationsClerk` may reverse a `POSTED` transaction, moving it to `REVERSED`; the attempt against a transaction in any other status is rejected with `ERR_INVALID_STATE_TRANSITION`, and once the batch has moved on to `SETTLED` — or was `CANCELLED` — the window has closed and the attempt fails with `ERR_REVERSAL_WINDOW_CLOSED`. Reversal credits the account's `ledger_balance_cents` back by the `amount_cents` of a debit, or debits it back for a credit. Any `OverdraftFee` rows whose `transaction_id` names the reversed transaction and that are still `ASSESSED` become `VOIDED` — a fee that never posted is never debited — and their voided amounts are added to the account's `lifetime_fees_waived_cents`. The account's derived aggregates are recomputed and its `version` increments.

### 3.5. Settling the Batch: Sustained Overdraft, Restriction, and Charge-Off

Settlement converts a sealed batch into permanent ledger fact. An `OperationsClerk` settles a `SEALED` batch — settling from any other status is an invalid transition — but only once every earlier-dated batch of the same program has reached `SETTLED` or `CANCELLED`; if an earlier batch is still open or sealed, the settle is rejected with `ERR_EARLIER_BATCH_UNSETTLED`. Settlement first moves every `ASSESSED` fee created by the seal to `POSTED`, stamping `posted_date` with the batch's business date and debiting each fee's amount from its account's `ledger_balance_cents` — this is the moment fees finally touch the ledger they were kept out of during the seal.

With fees posted, the sustained-overdraft day count runs for every `ACTIVE` or `RESTRICTED` account of the batch's program — including accounts with no activity in this batch — again in account `created_at` order. An account whose post-fee ledger is negative has its `consecutive_negative_business_days` incremented; an account whose ledger is zero or positive resets that counter to zero, and if it was `RESTRICTED`, it cures back to `ACTIVE` with `restricted_business_days` reset to zero and its `version` incremented.

When an `ACTIVE` account's incremented count reaches or exceeds the program's `sustained_overdraft_days_threshold`, the account is restricted: its `status` becomes `RESTRICTED`, `restricted_business_days` resets to zero, and its `version` increments. Unless the program is `SUSPENDED`, the same settle assesses the one-time sustained fee — an `OverdraftFee` of `fee_type` `SUSTAINED` for `sustained_overdraft_fee_cents`, born directly in `POSTED` status with `transaction_id` null, `posted_date` set to the batch's business date, exempt from both daily caps and the de minimis test, and debited from the ledger immediately — and adds the amount to `lifetime_fees_assessed_cents`. Restriction also triggers a steering nudge: an **EducationOffer** of type `OVERDRAFT_LINE_OF_CREDIT` with `trigger_reason` `SUSTAINED_OD` is auto-created, subject to the same steering caps described below.

An account already `RESTRICTED` whose ledger is still negative instead has `restricted_business_days` incremented, and when that count reaches or exceeds `charge_off_grace_business_days`, the account is charged off. Charge-off moves the account to `CLOSED_CHARGEOFF`, sets `charged_off_cents` and `charge_off_original_cents` to the magnitude of the negative ledger, sets `recovered_cents` to zero, zeroes `ledger_balance_cents`, and increments `version`. The cascade resolves the account's open items in the same motion: every waiver request still in `PENDING_SUPERVISOR`, `PENDING_MANAGER`, or `PENDING_COMPLIANCE` is moved to `DENIED_FINAL`, and every education offer still `OFFERED` is moved to `EXPIRED`.

After day counting completes, the settle runs its steering sweep. For each `ACTIVE` or `RESTRICTED` account of the program, again in `created_at` order, the server considers the trailing closed date window of `steering_window_days` calendar days ending on the batch's `business_date` — that is, from `business_date` minus (`steering_window_days` minus one) through `business_date` inclusive. It counts fees — both `OVERDRAFT` and `SUSTAINED` — whose `posted_date` falls inside the window and whose `status` is `POSTED` or `WAIVED`; `ASSESSED` and `VOIDED` fees never count. If that count reaches or exceeds `steering_fee_count_threshold`, and the account has no offer currently `OFFERED` and no offer of any status created within the window, the server auto-creates an `EducationOffer` of type `OVERDRAFT_LINE_OF_CREDIT` with `trigger_reason` `FEE_THRESHOLD`, born `OFFERED` with `expires_at` set to the settle clock plus `offer_expiry_days`.

### 3.6. Fee Waivers: Routing, Allocation, Decisions, and Appeals

Fee relief enters through a **FeeWaiverRequest**, submitted by an `AccountHolder` (against their own account), a `Teller`, a `Supervisor`, or a `Manager`. The submission names the `account_id`, an ordered, non-empty `fee_ids` list, a `kind` of `FULL`, `FIXED_AMOUNT`, or `PERCENT_BPS`, and a `reason_code` of `HARDSHIP`, `BANK_ERROR`, `FIRST_TIME`, or `GOODWILL`. A `FIXED_AMOUNT` request must carry `amount_cents`, and a `PERCENT_BPS` request must carry `percent_bps` between 1 and 10000; a missing kind-specific field, an empty `fee_ids`, or any other malformed body is rejected with `ERR_INVALID_REQUEST`. Every listed fee must belong to the named account and be `ASSESSED` or `POSTED` at submit time — a listed fee that is already `WAIVED` or `VOIDED`, or that belongs to another account, is rejected with `ERR_FEE_NOT_WAIVABLE`. For `FIXED_AMOUNT`, the `amount_cents` must additionally be positive and must not exceed the sum of the listed fees' outstanding amounts at submit; violating either bound is rejected with `ERR_WAIVER_AMOUNT_INVALID` (HTTP 422).

The requested total is computed by allocation across the listed fees in a pinned order: fees are visited by `created_at` earliest first, ties broken by smaller `amount_cents`, and never by identifier. Under `FULL`, each item's allocation is its full `outstanding_cents`. Under `FIXED_AMOUNT`, the allocation waterfalls left to right: each item receives the smaller of the remaining requested amount and its `outstanding_cents`, and the remaining amount shrinks as the walk proceeds. Under `PERCENT_BPS`, each item's allocation is its `outstanding_cents` multiplied by `percent_bps` and divided by 10000, rounded half up **per item first**, with the total formed by summing the rounded per-item amounts — rounding after summing can differ by a cent and is forbidden. The summed total becomes the request's `computed_total_cents`, which drives authority routing. The request's `routing_band` reflects that total alone: at or below 5,000 cents (fifty dollars) the band is `TELLER`; above 5,000 cents and at or below 20,000 cents (two hundred dollars) it is `SUPERVISOR`; above 20,000 cents and at or below 100,000 cents (one thousand dollars) it is `MANAGER`; and anything above 100,000 cents routes to `COMPLIANCE`.

The initial `status` depends on both the band and who asked. When a staff member — a `Teller`, `Supervisor`, or `Manager` — submits a request whose total sits at or below the teller cap, the request is auto-approved and born `APPLIED`: the allocations are applied immediately, exactly as at approval time. An `AccountHolder`-created request never auto-approves; even a one-dollar holder request routes to `PENDING_SUPERVISOR` at minimum. Staff or holder requests above the teller cap but within the supervisor cap are born `PENDING_SUPERVISOR`; totals above the supervisor cap but within the manager cap are born `PENDING_MANAGER`; totals above the manager cap are born `PENDING_COMPLIANCE`. For every pending-born request, the system creates its **WaiverRequestItem** rows — each linking `waiver_request_id` to a `fee_id` — with `waived_cents` zero, because per-item amounts for pending requests are only computed when the request is applied. Waiver items are immutable once written, and the collection can be listed with optional `waiver_request_id` and `fee_id` filters. The request itself records `created_by_user_id` and `created_by_role` from the caller's headers for segregation of duties, and requests can be listed with optional `account_id` and `status` filters.

Approval is band-scoped. A `PENDING_SUPERVISOR` request may be approved by a `Supervisor`, `Manager`, or `ComplianceOfficer`; a `PENDING_MANAGER` request only by a `Manager` or `ComplianceOfficer` — a `Supervisor` attempting it fails with `ERR_WAIVER_EXCEEDS_AUTHORITY`; and a `PENDING_COMPLIANCE` request only by a `ComplianceOfficer`, with `Supervisor` or `Manager` attempts likewise failing `ERR_WAIVER_EXCEEDS_AUTHORITY`. Whoever approves, two guards always run, per the precedence of §2.9 and §2.10: the approver's `X-User-ID` must differ from the request's `created_by_user_id`, else `ERR_SELF_APPROVAL_FORBIDDEN`, and every listed fee must still be `ASSESSED` or `POSTED` at that moment — if another request has already waived one, the approval is rejected with `ERR_FEE_STATE_CHANGED`. On approval the allocation is recomputed against current outstanding amounts using the same pinned ordering, each item's `waived_cents` is written, each fee's `waived_cents` grows by its allocation, and any fee whose `outstanding_cents` thereby reaches zero flips to `WAIVED` — partial waivers leave a fee in its current status with a reduced `outstanding_cents`, and only a zero outstanding produces `WAIVED`. The account's ledger is credited by the total waived amount, `lifetime_fees_waived_cents` grows by the same total, `decided_by_user_id` is set to the approver, and the request becomes `APPLIED`.

Denial mirrors the band structure but never moves money. Denying a `PENDING_SUPERVISOR` request — available to `Supervisor`, `Manager`, or `ComplianceOfficer` — moves it to `DENIED` with `denied_band` set to `SUPERVISOR`; denying a `PENDING_MANAGER` request — `Manager` or `ComplianceOfficer` — moves it to `DENIED` with `denied_band` `MANAGER`; denying a `PENDING_COMPLIANCE` request — `ComplianceOfficer` only — moves it to `DENIED_FINAL` with `denied_band` `COMPLIANCE`. Every denial records `decided_by_user_id`, and the self-decision guard applies to denials exactly as to approvals: the denier must not be the creator, else `ERR_SELF_APPROVAL_FORBIDDEN`.

Two escape valves keep a stalled request moving. Escalation lifts a pending request one band — `PENDING_SUPERVISOR` to `PENDING_MANAGER`, available to a `Supervisor` or `Manager`, and `PENDING_MANAGER` to `PENDING_COMPLIANCE`, available to a `Manager`. Appeal reopens a denied request from below: an `AccountHolder`, `Teller`, `Supervisor`, or `Manager` may appeal a `DENIED` request, and the destination depends on where it died — a request whose `denied_band` is `SUPERVISOR` re-enters at `PENDING_MANAGER`, while one whose `denied_band` is `MANAGER` re-enters at `PENDING_COMPLIANCE`. `DENIED_FINAL` is terminal: there is no appeal from a compliance-stage denial, and attempting any action against it is an invalid state transition. Recall from §3.5 that a charge-off forcibly resolves any still-pending requests to `DENIED_FINAL`.

### 3.7. Program Change Notices and Disclosure Windows

Changing a governed parameter is deliberately slow. A `ProgramAdmin` begins by creating a **ProgramChangeNotice** naming the `program_id`, the `parameter` being changed, and the `new_value`. Six parameters are changeable, and the notice's value is always a string — an integer rendered as a string for cent and count parameters, or the enum member itself for posting order: `FEE_AMOUNT` retargets the program's `fee_amount_cents`, `DAILY_CAP_CENTS` retargets `daily_fee_cap_cents`, `MAX_DAILY_FEES` retargets `max_daily_fees_count`, `DE_MINIMIS` retargets `de_minimis_threshold_cents`, `POSTING_ORDER` retargets `posting_order_policy`, and `SUSTAINED_FEE` retargets `sustained_overdraft_fee_cents`. Creation snapshots the current value of the mapped field into `old_value`, births the notice in `DRAFT` status, supersedes any existing `DRAFT` notice for the same program and parameter — the older draft moves to `SUPERSEDED` — and increments the program's `version`. Because that version moves on every notice creation, the create call carries the optimistic-concurrency guard of §2.8: a request whose `expected_program_version` no longer matches the program's current `version` is rejected with `ERR_STALE_PROGRAM_VERSION`. Notices can be listed with optional `program_id`, `parameter`, and `status` filters.

Issuing a draft is also a `ProgramAdmin` action, and it starts the disclosure clock: `sent_at` is stamped from the logical clock and `effective_at` is computed as `sent_at` plus the program's `notice_window_days` calendar days. Issuance is refused — with `ERR_NOTICE_WINDOW_OVERLAP` — if any other notice for the same program and parameter is already `ISSUED` with a window that would overlap the new one. Each window is the half-open interval that includes its `sent_at` instant and runs up to but does not include its `effective_at` instant, so a new issue whose `sent_at` coincides exactly with the prior notice's `effective_at` does not overlap and is permitted. A successful issue moves the notice from `DRAFT` to `ISSUED`.

Activation is reserved for a `ComplianceOfficer`, separating the communicator from the applier per §2.9. Activation requires the program to be `ACTIVE` — a suspended program refuses activation with `ERR_PROGRAM_SUSPENDED` — and requires the logical clock to have reached `effective_at`; an early attempt is rejected with `ERR_NOTICE_WINDOW_NOT_ELAPSED`. A successful activation moves the notice from `ISSUED` to `EFFECTIVE`, writes the `new_value` into the mapped program field, and increments the program's `version`.

Withdrawal, a `ProgramAdmin` action, abandons a notice before it bites: a `DRAFT` notice may be withdrawn at any time, and an `ISSUED` notice may be withdrawn only while the clock has not yet reached its `effective_at` — an already-effective notice cannot be withdrawn. Either path lands in `WITHDRAWN`.

### 3.8. Customer Steering and Education Offers

Beyond the two automatic creation paths of §3.5, a `Teller` may create an **EducationOffer** manually, naming the `account_id` and an `offer_type` of `LINKED_SAVINGS`, `OVERDRAFT_LINE_OF_CREDIT`, or `COUNSELING`. Manual creation carries the account-scoped optimistic-concurrency guard of §2.8 — a request whose `expected_account_version` no longer matches the account's current `version` is rejected with `ERR_STALE_ACCOUNT_VERSION` — and it has two standing effects: any offer currently `OFFERED` on the account is moved to `SUPERSEDED`, and the account's `version` increments. The new offer is born `OFFERED` with `trigger_reason` `MANUAL` and `expires_at` set to the creation clock plus the program's `offer_expiry_days`. The automatic paths, by contrast, only fire when no offer is currently `OFFERED` and none was created within the trailing window, so supersession is in practice a manual-creation effect. Offers can be listed with optional `account_id` and `status` filters.

Only the account holder can answer an offer. Accepting moves `OFFERED` to `ACCEPTED`; declining moves `OFFERED` to `DECLINED`. Both actions require the logical clock to be on or before `expires_at` — a late answer is rejected with `ERR_OFFER_EXPIRED` — and require the owning account to be `ACTIVE` or `RESTRICTED`; an offer on a closed account cannot be answered, failing with `ERR_ACCOUNT_CLOSED`. Expiry itself is lazy: when the clock has passed `expires_at`, the offer surfaces as `EXPIRED` the next time it is read or acted upon, and the charge-off cascade of §3.5 also forces still-`OFFERED` offers to `EXPIRED`.

### 3.9. Regulatory Reporting and Scrutiny Metrics

The compliance surface is the **RegulatoryReport**, created by a `ProgramAdmin` or `ComplianceOfficer` with a `program_id`, a `period_start`, and a `period_end`, all in `YYYY-MM-DD` form. The period is a closed interval: a `period_end` earlier than `period_start` is rejected as a malformed request with `ERR_INVALID_REQUEST`. Periods for a program must tile without seams — no overlap and no gap. A period that intersects any existing report's closed interval is rejected with `ERR_REPORT_PERIOD_OVERLAP`, and this overlap check runs before the gap check; then, unless this is the program's first report (which may start on any date), the `period_start` must be exactly one day after the previous report's `period_end`, else the creation is rejected with `ERR_REPORT_PERIOD_GAP`. A new report is `OPEN`, and its five computed fields — `revenue_provisional_cents`, `revenue_final_cents`, `waiver_ratio_bps`, `avg_fees_per_overdrafter_centi`, and `scrutiny_flag` — remain null until finalization. Reports can be listed with optional `program_id` and `status` filters.

Finalization, performed by a `ComplianceOfficer`, computes the metrics. A fee's period date is its batch's `business_date` — except `SUSTAINED` fees, which use their own `posted_date` — and `VOIDED` fees are excluded from every measure. Two revenue bases are produced. The provisional, accrual basis `revenue_provisional_cents` sums, over all fees whose period date falls inside the closed period and whose status is `ASSESSED`, `POSTED`, or `WAIVED`, each fee's `amount_cents` minus its `waived_cents`. The settled basis `revenue_final_cents` applies the same sum but over fees whose status is `POSTED` or `WAIVED` only, excluding `ASSESSED` fees; whenever any batch covering the period is sealed but not yet settled, identical period data therefore yields a final figure at or below the provisional one.

Two scrutiny ratios follow, both using floor division per §2.6. The waiver ratio `waiver_ratio_bps` divides the total `waived_cents` across the period's `POSTED` and `WAIVED` fees by the total `amount_cents` of those same fees, multiplies by 10000 to express the result in basis points, and discards any remainder; when no such fees exist the ratio is zero. The per-overdrafter average `avg_fees_per_overdrafter_centi` multiplies the count of the period's `POSTED` and `WAIVED` fees by 100, divides by the number of distinct accounts carrying at least one such fee, and discards any remainder; when no account has such a fee the average is zero. The `scrutiny_flag` is true exactly when the waiver ratio is strictly greater than 1500 basis points — that is, more than fifteen percent of assessed fee value was waived — or the average is at least 1200 hundredths, meaning twelve or more fees per overdrafter. Finalization also records `finalized_by_user_id` from the caller's header and moves the report from `OPEN` to `FINALIZED`.

Submission, also by a `ComplianceOfficer`, is the terminal step and enforces the last segregation-of-duties rule: the submitter's `X-User-ID` must differ from `finalized_by_user_id`, else the submission is rejected with `ERR_SELF_SUBMISSION_FORBIDDEN`. A successful submission moves the report from `FINALIZED` to `SUBMITTED`.

## 4. Endpoint Definitions

Operations that create a new resource — a program, an account, an election, a transaction, a batch, a waiver request, a notice, an offer, or a report — return a `201 Created` status code. Operations that modify an existing resource, including every state-transition action and the clock-setting capability, return a `200 OK` status code. The complete request and response shapes for each operation are defined by the narratives of §2 and §3; the table below is an index, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/_clock/set_current_utc` | Set the server's logical clock | ProgramAdmin |
| POST | `/v1/programs` | Create an overdraft program (status ACTIVE) | ProgramAdmin |
| GET | `/v1/programs/{id}` | Get a program | All roles |
| POST | `/v1/programs/{id}/suspend` | Suspend a program | ProgramAdmin |
| POST | `/v1/programs/{id}/resume` | Resume a suspended program | ProgramAdmin |
| POST | `/v1/accounts` | Open a deposit account under a program | Teller, ProgramAdmin |
| GET | `/v1/accounts` | List accounts (filterable) | All roles |
| GET | `/v1/accounts/{id}` | Get an account | All roles |
| POST | `/v1/accounts/{id}/close` | Voluntarily close an account | Teller, ProgramAdmin |
| POST | `/v1/accounts/{id}/opt-in-election` | Create the account's single opt-in election | AccountHolder, Teller |
| GET | `/v1/opt-in-elections` | List opt-in elections | All roles |
| GET | `/v1/opt-in-elections/{id}` | Get an opt-in election | All roles |
| POST | `/v1/opt-in-elections/{id}/revoke` | Revoke an election | AccountHolder, Teller |
| POST | `/v1/opt-in-elections/{id}/reinstate` | Reinstate a revoked election | AccountHolder, Teller |
| POST | `/v1/transactions` | Authorize a transaction (recovery credit on charged-off accounts) | AccountHolder, Teller |
| GET | `/v1/transactions` | List transactions (filterable) | All roles |
| GET | `/v1/transactions/{id}` | Get a transaction | All roles |
| POST | `/v1/transactions/{id}/reverse` | Reverse a POSTED transaction while its batch is SEALED | OperationsClerk |
| POST | `/v1/batches` | Open a posting batch for a business date | OperationsClerk |
| GET | `/v1/batches` | List batches (filterable) | All roles |
| GET | `/v1/batches/{id}` | Get a batch | All roles |
| POST | `/v1/batches/{id}/seal` | Seal a batch: sweep, order, post, assess fees | OperationsClerk |
| POST | `/v1/batches/{id}/settle` | Settle a sealed batch: post fees, count days, steer | OperationsClerk |
| POST | `/v1/batches/{id}/cancel` | Cancel an unsealed, empty OPEN batch | OperationsClerk |
| GET | `/v1/fees` | List fees (filterable) | All roles |
| GET | `/v1/fees/{id}` | Get a fee | All roles |
| POST | `/v1/fee-waiver-requests` | Submit a waiver request (routes or auto-applies) | AccountHolder, Teller, Supervisor, Manager |
| GET | `/v1/fee-waiver-requests` | List waiver requests (filterable) | All roles |
| GET | `/v1/fee-waiver-requests/{id}` | Get a waiver request | All roles |
| POST | `/v1/fee-waiver-requests/{id}/approve` | Approve a pending request within authority band | Supervisor, Manager, ComplianceOfficer |
| POST | `/v1/fee-waiver-requests/{id}/deny` | Deny a pending request | Supervisor, Manager, ComplianceOfficer |
| POST | `/v1/fee-waiver-requests/{id}/escalate` | Move a pending request up one authority band | Supervisor, Manager |
| POST | `/v1/fee-waiver-requests/{id}/appeal` | Appeal a DENIED request to the next higher band | AccountHolder, Teller, Supervisor, Manager |
| GET | `/v1/waiver-items` | List waiver request items (filterable) | All roles |
| GET | `/v1/waiver-items/{id}` | Get a waiver request item | All roles |
| POST | `/v1/notices` | Create a DRAFT program-change notice | ProgramAdmin |
| GET | `/v1/notices` | List notices (filterable) | All roles |
| GET | `/v1/notices/{id}` | Get a notice | All roles |
| POST | `/v1/notices/{id}/issue` | Issue a DRAFT notice, starting its disclosure window | ProgramAdmin |
| POST | `/v1/notices/{id}/activate` | Activate an ISSUED notice after its window elapsed | ComplianceOfficer |
| POST | `/v1/notices/{id}/withdraw` | Withdraw a DRAFT or ISSUED notice | ProgramAdmin |
| POST | `/v1/education-offers` | Banker creates a steering offer | Teller |
| GET | `/v1/education-offers` | List education offers (filterable) | All roles |
| GET | `/v1/education-offers/{id}` | Get an education offer | All roles |
| POST | `/v1/education-offers/{id}/accept` | Account holder accepts an offer | AccountHolder |
| POST | `/v1/education-offers/{id}/decline` | Account holder declines an offer | AccountHolder |
| POST | `/v1/reports` | Create a regulatory report for a closed period | ProgramAdmin, ComplianceOfficer |
| GET | `/v1/reports` | List reports (filterable) | All roles |
| GET | `/v1/reports/{id}` | Get a report | All roles |
| POST | `/v1/reports/{id}/finalize` | Finalize a report, computing its metrics | ComplianceOfficer |
| POST | `/v1/reports/{id}/submit` | Submit a finalized report | ComplianceOfficer |

## 5. Error Code Catalogue

The catalogue below enumerates every machine-readable error identifier and its HTTP status. The conditions that trigger each error are defined by the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_ACCOUNT_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_ACCOUNT_RESTRICTED` | 409 Conflict |
| `ERR_ACCOUNT_CLOSED` | 409 Conflict |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_FEE_NOT_WAIVABLE` | 409 Conflict |
| `ERR_PROGRAM_SUSPENDED` | 409 Conflict |
| `ERR_STALE_DISCLOSURE_VERSION` | 409 Conflict |
| `ERR_NOTICE_WINDOW_NOT_ELAPSED` | 409 Conflict |
| `ERR_NOTICE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_REPORT_PERIOD_GAP` | 409 Conflict |
| `ERR_NON_BUSINESS_DAY` | 422 Unprocessable Entity |
| `ERR_REVERSAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_EARLIER_BATCH_UNSETTLED` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_BATCH_ALREADY_EXISTS` | 409 Conflict |
| `ERR_ELECTION_ALREADY_EXISTS` | 409 Conflict |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 409 Conflict |
| `ERR_SELF_SUBMISSION_FORBIDDEN` | 409 Conflict |
| `ERR_FEE_STATE_CHANGED` | 409 Conflict |
| `ERR_CLOSE_NEGATIVE_BALANCE` | 409 Conflict |
| `ERR_OPEN_ITEMS_BLOCK_CLOSE` | 409 Conflict |
| `ERR_WAIVER_EXCEEDS_AUTHORITY` | 409 Conflict |
| `ERR_WAIVER_AMOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_RECOVERY_EXCEEDS_CHARGEOFF` | 422 Unprocessable Entity |
| `ERR_STALE_PROGRAM_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ACCOUNT_VERSION` | 412 Precondition Failed |
