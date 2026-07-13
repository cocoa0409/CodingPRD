# Worklog — task_0559_restaurant_supply

## Step 1: Create Task Directory — 2026-07-08T00:00:00.000Z

Created `tasks/task_0559_restaurant_supply/` and `tasks/task_0559_restaurant_supply/workspace/`.

## Step 2: Generate Scaffold — 2026-07-08T04:00:00.000Z

All checks pass. The scaffold is complete and internally consistent.

Generated a fresh **Expert**-difficulty scaffold for task_0559_restaurant_supply (Restaurant Supply & Smallwares Distribution, WebstaurantStore style) — three files, all passing `scaffold_lint.py` (`VERDICT: clean lint`).

**Files written**: `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8), `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9).

**Scaffold contents**
- **12 entities**: Account, TaxExemptCertificate, Product, PurchaseOrder, OrderLine, Shipment, ReturnAuthorization, ReturnLine, Dock, DeliveryAppointment, InstallCrew, InstallJob.
- **7 state machines**: Account (ACTIVE↔SUSPENDED), TaxExemptCertificate (cyclic — REJECTED→SUBMITTED resubmit + clock-driven EXPIRED), PurchaseOrder (parallel lifecycle × payment dimensions + compensating cancel), Shipment, ReturnAuthorization (branching + APPROVED→REQUESTED revert), DeliveryAppointment, InstallJob.
- **5 calculations**: `line_tier_pricing` (each/case/pallet decomposition), `order_tax` (round-per-line-then-sum, tax-exempt gating), `freight_quote` (provisional-vs-final dual variant + parcel/LTL/liftgate/free-freight), `restock_refund` (sealed-vs-opened dual variant), `account_outstanding` (credit aggregation).
- **1 concurrency rule**: OCC on Account.version at order confirm (credit reservation).
- **12 validation priorities**, **48 error codes**, **60 endpoints** (flat multi-collection API, `api_prefix: /`; includes a `/_clock/set_current_utc` test endpoint defaulting to 2026-05-01), **3 RBAC roles** (AccountManager/WarehouseOps opaque; Buyer entity_backed:Account).

**Difficulty design (§1.8)**: all **9 rules × 2 = 18 instances**, each grounded with executable setup chains and pre-computed literal asserts.

**Corner design (§1.9)**: **41 instances** (33 active recipes + 8 `excluded_because` stubs pointing to §1.8).

Note: endpoint count (60) and error count (48) run above the Expert guideline bands, driven by the scenario's eight distinct feature areas each needing full CRUD + FK reverse-reachability GETs.

## Step 3: Copy Shared Files — 2026-07-08T04:05:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-08T04:15:00.000Z

Generated `workspace/PRD.md`. 323 lines, 24 section headings — 10 §2 subsections (RBAC, response envelope, pagination, common properties/versioning, monetary/weight precision, logical clock, nested retrieval + filtered listing, cascading consistency, account-version OCC, credit ledger) and 9 §3 workflow subsections, plus §4 endpoint table (~60 endpoints) and §5 error table (48 errors).

Hard contracts: Contract 1 (field-name coverage 66/66) PASS; Contract 2 (rule coverage: validations, OCC, state machines, calculations, side-effects) PASS; Contract 3 (§3 path purity, 0 leaked paths/methods) PASS. Neither withheld design file was accessed.

## Step 5: Generate Unit Tests — 2026-07-08T04:45:00.000Z

(Note: first launch of Steps 5+6 was cut off by an API ConnectionRefused error with only partial output; partials cleaned and both re-launched fresh.)

Generated complete test infrastructure for `task_0559_restaurant_supply`.

**Stage 1 — `test_helpers/`** (9 files): `types.py` (13 entity TypedDicts + status/role enums; all entities carry `updated_at`/`version`), `api_errors.py` (49 error IDs + HTTP-status map), `api_client.py` (60 endpoint methods), `factories.py`, `assertions.py`, `constants.py`, `test_users.py` (opaque AccountManager/WarehouseOps constants + `make_buyer_headers(account_id)`), `fixtures.py`, `__init__.py`.

**Stage 2 — `test_suite/`** (conftest + 8 test files): **64 tests total**.
- **Queue A (Difficulty): 34 tests** across 17 of 18 instances (2 each).
- **Queue B (Corner): 30 tests** across all 30 non-stub instances (1 each). The 11 `excluded_because:` stubs were not translated.

**Skipped instances (1):** `Difficulty/cross_entity_state_dependency/shipment_requires_order_confirmed` — PRD §3.7 only names `ERR_ORDER_NOT_CONFIRMED` for *booking* a shipment, not for *creating* one; create-side coverage is only endpoint-titular (C2-forbidden). Fails PRD-first coverage+unique-derivability filter → skipped, gap left as gap.

Verification: all 18 files compile; every `api.*`/`fixtures.*` call resolves; every docstring ends with exactly one `Design:` tag (47 unique tags = 17 difficulty + 30 corner); every quoted PRD citation survives verbatim substring check; no scaffold/§1.x references. Computed expectations re-derived and match design YAMLs.

## Step 6: Generate Implementation — 2026-07-08T04:45:00.000Z

Built a complete Python + Flask REST API in `workspace/implementation/`.

**Files:** `start.sh` (foreground launcher; reads `$PORT` default 10000, binds `0.0.0.0`, guards `pip install` behind flask-import check, `exec`s server), `requirements.txt` (Flask==3.0.3), `app.py` (single-module; in-memory dicts, empty on boot, no seeding, no disk).

**Endpoints:** 62 routes (all 61 PRD/scaffold endpoints + `GET /` health).

**Behaviors verified by live testing:** response envelope + pagination (defaults 10/0, clamp 1–100), UUID ids, ISO-8601 ms timestamps, RBAC 3 roles + Buyer ownership, error ordering (header→role→existence→ownership→state→business→OCC), tiered pallet/case/each pricing, per-line round-half-up tax (Decimal) + tax-exempt suppression, confirm allocation/backorder cascade + inventory decrement + reorder recompute, OCC on `expected_account_version` (412), credit-limit (402), account-suspended (409), cancel compensation, parallel invoice/pay dimension, outstanding/credit-available ledger, provisional vs final freight (PARCEL/LTL breakpoint, liftgate, free-freight threshold), returns restock fee (15% sealed / 25% opened) + refund cascade, logical clock (default 2026-05-01) + cert auto-expiry, dock half-open overlap, install 60-min buffer + equipment lead-time.

start.sh confirmed: reads `$PORT`, binds `0.0.0.0`, foreground via `exec`.

## Step 7: Run Tests and Iterate — 2026-07-08T05:10:00.000Z

The task was already in a clean, passing state. The baseline 8-round parallel sweep passed on the first iteration with no fixes needed.

- **Iterations run:** 1 (baseline sweep). All 8 parallel rounds passed 64/64 tests, 0 failures / 0 errors in every round. No flakiness surfaced.
- **Tests deleted:** None.
- **Fixes applied to `test_helpers/`:** None required.
- **Fixes applied to `implementation/`:** None required.

Orchestrator re-ran a confirming 8-round parallel sweep to persist the final `results.{1..8}.json` artifacts: all 8 rounds = passed=64 total=64 failed=0 errors=0.

## Step 8: Finalize PRD — SKIPPED — 2026-07-08T05:12:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. PRD.md already determined every behavior the implementation exhibits at the Step-7-touched sites. `PRD_FINALIZED.md` not produced.

## Step 9: Complete PRD — 2026-07-08T05:20:00.000Z

Produced `workspace/PRD_COMPLETED.md` from `PRD.md` (Step 8 skipped, no PRD_FINALIZED.md).

- **Line counts:** PRD.md 323 lines / 44,835 chars → PRD_COMPLETED.md 323 lines / 45,799 chars (+964 chars, 0 net lines).
- **Counts:** 5 ambiguity-pins, 1 mismatch-revision. All six edits in-paragraph; no new sections.

Changes:
- §2.3 Pagination — insert — ambiguity — out-of-range `limit`/`offset` clamped to nearest bound (not rejected); non-integer values yield `ERR_INVALID_REQUEST` (app.py:507-523).
- §3.7 Shipping — revise — mismatch — shipment create validates only order existence; `CONFIRMED` requirement deferred to booking (app.py:1049-1075).
- §3.7 Shipping — insert — ambiguity — booking recomputes `shipping_mode` from final allocated-weight variant (may flip from QUOTED-time mode) (app.py:1110-1114).
- §3.8 Returns — insert — ambiguity — adding a return line to a return not in `REQUESTED` yields `ERR_RETURN_NOT_REQUESTED` (app.py:1219-1220).
- §3.9 Scheduling — insert — ambiguity — `location` defaults to empty string when omitted (app.py:1374).
- §3.9 Scheduling — insert — ambiguity — install lead-time check applies only when order has non-null `confirmed_at` (app.py:1504-1507).
