# Worklog — task_0797_textbook_rental

## Step 1: Create task directory — 2026-07-08T03:21:32.000Z

Created `tasks/task_0797_textbook_rental/` and `tasks/task_0797_textbook_rental/workspace/`. Verified `./INSTRUCTION.md` exists at project root for Step 3 copy.

## Step 2: Generate scaffold — 2026-07-08T04:06:00.000Z

All three artifacts are complete, parse cleanly, and pass `scaffold_lint.py` with a clean verdict. Here is the summary.

## Generated: `tasks/task_0797_textbook_rental/`

**Domain / profile:** Textbook & Course-Material Rental (Chegg-style). Primary archetype **pricing_engine** + secondary **workflow_orchestration**; layers: dual-variant calculation, cascading side effects, rate/threshold triggers, optimistic concurrency. Flat topology, **parallel** state-machine shape, peer roles, immediate consistency. Calibrated **Expert**.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **10 entities** — CatalogItem, InventoryUnit, Customer, SubscriptionPlan, Subscription, Order, Rental, ReturnShipment, BuybackQuote, WalletTransaction
- **33 endpoints** (api_prefix `/`, flat multi-collection; includes `/_clock/set_current_utc` with fixed default `2026-03-01T00:00:00Z`)
- **28 errors**, **30 validations** (priority-ordered auth→existence→state→safety→referential→temporal→constraint→fiscal)
- **5 state machines** — Order (parallel payment×fulfillment axes), Rental, ReturnShipment (branching fork by inspection outcome), BuybackQuote (branching fork at inspection + supersede), Subscription
- **10 calculations** — order_charge (quoted/final dual-variant with loyalty circular credit), buyback_price (quoted/assessed dual-variant), late_fee (grace threshold), damage_fee (non-linear min-cap), rental_due_date, subscription_period, subscription_proration, extension_fee, wallet_balance, confirm_unit_selector
- **1 concurrency rule** — buyback re-quote supersede, OCC on `Customer.version` (412)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 18 instances (2 per each of the 9 rules), all with executable `setup_api_calls` chains and pre-computed literal asserts (e.g., rental final 7750/10000, buyback 2700→2250, damage cap 3500, proration 1251, replacement cascade wallet 34000).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** 31 active corner instances across entities/state-machines/calculations/validations/endpoints/RBAC/OCC (every error triggerable, both OCC polarities, member-discount, proration, EBOOK access window, pagination envelope) plus 6 `excluded_because` stubs referencing §1.8 instances.

**Verification:** all three files `yaml.safe_load` clean; `scaffold_lint.py` → `VERDICT: clean lint` (331 calls checked, all FK reverse-reachability satisfied); no forbidden concurrency vocabulary; enum-closure and trigger↔side-effect consistency audited (removed a dead `PARTIALLY_REFUNDED` value; added `Rental.customer_id` for ownership). Orchestrator confirmed all three files `safe_load` clean.

## Step 3: Copy INSTRUCTION.md — 2026-07-08T04:06:43.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-08T04:13:22.000Z

The PRD is complete and all three hard contracts pass.

## Summary

Generated `workspace/PRD.md` (268 lines) from the scaffold.

**Structure**
- 5 top-level sections; §2 has 9 subsections (2.1–2.9, including the verbatim §2.2 envelope), §3 has 7 domain-derived lifecycle subsections (catalog/inventory, customers+wallet+subscriptions, ordering, fulfilment, loan cycle, inspection+close, buyback).
- **33 endpoints** documented in the §4 table — matches all 33 scaffold endpoints.
- §5 error table lists all 28 error IDs with HTTP status.
- **Word count: 5,641 words.**

**Hard-contract verification (mechanical)**
- Contract 1 (Field-Name Coverage): 71/71 required identifiers present, 0 missing — PASS.
- Contract 3 (§3 Path Purity): 397 backtick tokens in §3, 0 paths/bare methods — PASS.
- Contract 2 (Rule Coverage): all 10 calculations rendered operator-free with constants embedded; all state transitions across Order, Rental, ReturnShipment (3-way fork), BuybackQuote (7 transitions), Subscription with from/to states, preconditions↔error IDs, cascades; OCC rule (`expected_customer_version` → `ERR_STALE_VERSION` 412); 11-tier validation priority in §2.8 — PASS.

**Confirmation:** Neither design yaml was read/grepped/referenced.

One note: scaffold references `QUOTE_VALIDITY_DAYS` for `quote_expires_at` but assigns no numeric value, so PRD describes it as "the quote validity window" without inventing a number.

## Step 5: Generate unit tests — 2026-07-08T04:29:00.000Z

Test infrastructure generation complete for `task_0797_textbook_rental`.

**Stage 1 — `test_helpers/` (9 files):** `types.py`, `api_client.py` (34 endpoint methods), `api_errors.py` (28 error IDs + HTTP-status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque admin/warehouse constants + `make_customer_headers()`), `fixtures.py` (composite setups: paid/confirmed rental, return-opened, inspected-rental, accepted/revised buyback, active subscription), and `__init__.py`.

**Stage 2 — `test_suite/` (conftest + 7 test files, 67 test functions).**

**Coverage (design-index-only):**
- **Queue A (Difficulty): 36 tests** — all 18 instances across 9 rules, each with exactly 2 tests.
- **Queue B (Corner): 31 tests** — all 31 non-stub instances, each 1 test.
- 6 `excluded_because` stubs correctly not translated.

**Instances skipped: none.**

**Two derivability adjustments (kept, not skipped):**
- `create_catalog_item_success`: asserts 201 + `edition` echo, does not hard-code `version==1` (PRD doesn't pin initial value).
- `buyback_accept_rejected_exactly_at_expiry_instant` + subscription-adjacency: read returned `quote_expires_at`/`period_end` and set clock to that instant rather than hard-coding an unstated constant.

Every test docstring carries verbatim PRD citations + single `Design:` tag. 67 tests collected cleanly. Orchestrator confirmed collection.

## Step 6: Generate implementation — 2026-07-08T04:29:00.000Z

Built complete Python + Flask implementation at `workspace/implementation/`.

**Files:** `app.py` (single-module server: routes, calculations, state machines, RBAC), `requirements.txt` (flask), `start.sh` (executable).

**Endpoints: all 33** — clock, catalog, inventory-units, customers, wallet, subscription-plans, subscriptions(+cancel), orders(create/pay/confirm/cancel/list/get), rentals(extend/return/list/get), return-shipments inspect, buyback-quotes(create/accept/inspect/respond-revision/list/get).

**Storage:** in-memory dicts keyed by id + module-level logical clock (default `2026-03-01T00:00:00Z`) + monotonic `_seq`. No seeding, no disk/SQLite. Resets on boot.

**start.sh:** reads `$PORT` (default 10000), binds `0.0.0.0`, foreground `exec python3 app.py`, guards pip install behind flask import check.

**Verified live:** envelope, ISO-8601 ms timestamps, X-User-ID/Role auth (3 roles), ownership 403s, existence-before-state precedence, RENT term multipliers + member discount, late fee, damage fee, final charge w/ loyalty ordering, lost-return replacement, buyback pricing, OCC ERR_STALE_VERSION 412, EBOOK license overlap + delivered-ebook cancel guard, subscription proration.

Spec gap: `QUOTE_VALIDITY_DAYS` undefined in scaffold/PRD; impl used 7 days (`quote_expires_at` returned so tests read it relative).

## Step 7: Test + fix loop — 2026-07-08T04:36:12.000Z

All 8 rounds pass 67/67. Clean sweep achieved. (Orchestrator confirmed all 8 results.N.json show passed=67 total=67.) Sweep run as 2 waves of 4 to avoid single-task host self-saturation.

**Iterations run:** 2 (initial sweep + 1 fix + confirming sweep).

**Tests deleted:** None. No PRD-silence or non-derivability issues found.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:**
- `workspace/implementation/app.py`, function `start_return` (POST `/rentals/<rid>/return`): reordered the two guard checks so the "return already open" check (a `ReturnShipment` in `LABEL_ISSUED` for this rental → `ERR_RETURN_ALREADY_OPEN`) runs **before** the `rental.status != "ACTIVE"` check (`ERR_RENTAL_NOT_ACTIVE`).

**Why:** PRD.md line 171 states that beginning a return moves the rental's status from `ACTIVE` to `RETURN_INITIATED`. Consequently, whenever a return is already open (a `LABEL_ISSUED` shipment exists) the rental is necessarily no longer `ACTIVE`. With the original ordering (ACTIVE checked first), `ERR_RETURN_ALREADY_OPEN` was unreachable dead code, contradicting the PRD's explicit definition of that error for exactly the return-twice scenario. `test_return_twice_returns_409` is PRD-faithful (verbatim-covered by PRD line 171, uniquely determined), so this was a STEP 3 implementation fix. The `ERR_RENTAL_NOT_ACTIVE` path remains reachable for rentals not ACTIVE without an open LABEL_ISSUED shipment.

The single failing test was a stable (non-flaky) failure present identically in all 8 rounds of the initial sweep.

## Step 8: Finalize PRD — 2026-07-08T04:37:59.000Z

Done. PRD_FINALIZED.md created with a single minimal edit.

- **Line counts:** PRD.md = 268, PRD_FINALIZED.md = 268 (0% line delta; one line revised in place).

### Change
- **§3.5 (Beginning a return), line 171 — revise — pinned guard-check ordering: the "return already open" check (`ERR_RETURN_ALREADY_OPEN`) is evaluated before the "rental must be ACTIVE" check (`ERR_RENTAL_NOT_ACTIVE`) — impl `app.py:913-917`.** Softened to "a rental that already has an open return (and has therefore left `ACTIVE`)" so `ERR_RENTAL_NOT_ACTIVE` stays reachable for closed rentals.

Pre-edit search enumerated `start_return`, `inspect_return` (only exit from RETURN_INITIATED/LABEL_ISSUED), and all `return_shipments`/`LABEL_ISSUED`/`RETURN_INITIATED` sites; wording consistent with all.

## Step 9: Complete PRD — 2026-07-08T04:43:17.000Z

Done. All changes in-paragraph (no lines added/removed).

**File deltas:** PRD_FINALIZED.md (268 lines, 39,681 chars) → PRD_COMPLETED.md (268 lines, 40,728 chars); char-delta +1,047. Ten paragraphs revised in place.

**Counts:** ambiguity-pins: 7 · mismatch-revisions: 3

**Changes:**
- §2.4 — insert — ambiguity — `version` begins at 1 (`app.py:174`).
- §2.3 Pagination — insert — ambiguity — ties on equal `created_at` broken by creation/persistence order (`_seq`, not `created_at`) under frozen clock (`app.py:342-345`).
- §3.2 Customers — revise — mismatch — dropped "unique `email`" claim (no uniqueness check/error in impl) (`app.py:455-463`).
- §3.3 Orders — revise — ambiguity — EBOOK `rental_term_days` = positive integer, not restricted to rental terms (`app.py:664-670`).
- §3.3 Orders — insert/revise — ambiguity+mismatch — EBOOK license-overlap window `[clock, clock+rental_term_days)`, access fields null until pay, compared vs prior non-refunded delivered ebook orders; overlap check runs after term-validity (impl checks tier-9 term before tier-8 overlap) (`app.py:682-696`).
- §3.4 Fulfilment — revise — mismatch — unit-selection final tiebreak by creation order (`_seq`), not `created_at` repeat (`app.py:792-794`).
- §3.4 Fulfilment — revise — mismatch — RENT confirmation drives copy AVAILABLE→RENTED directly; RESERVED never materialised (`app.py:810`).
- §3.6 Inspection — insert — ambiguity — `reported_condition` required when `is_lost` false, may be omitted (null) when true; omission on non-lost → `ERR_INVALID_REQUEST` (`app.py:979-984`).
- §3.7 Buyback — insert — ambiguity — quote validity window = 7 days (`app.py:48,1068`).
- §3.7 Buyback — insert — ambiguity — buyback-created InventoryUnit: `times_rented`=0, `acquisition_cost_cents`=credited price (`app.py:1120-1126`).

Unchanged (PRD already pins uniquely): RBAC/ownership, envelope, wallet math, subscription proration, order-charge/term/discount formulas, late/damage fee formulas + CLOSED fork, loyalty credit, final-charge settlement, buyback price rule + revision flow, state-machine guards/error codes.

---

**Pipeline complete.** All 9 steps finished. Final state: 67/67 tests pass across all 8 stability-sweep rounds. Artifacts: SCAFFOLD.yaml + 2 design yamls, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ + test_suite/ (67 tests), workspace/implementation/ (Flask, in-memory).
