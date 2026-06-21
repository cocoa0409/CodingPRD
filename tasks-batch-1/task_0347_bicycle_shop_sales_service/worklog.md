# Worklog — task_0347_bicycle_shop_sales_service

## Step 1: Create task directory — 2026-06-14T00:00:00.000Z

Created `tasks/task_0347_bicycle_shop_sales_service/` with `workspace/` subdirectory. Scenario: Bicycle Shop Sales & Service (Expert difficulty). Pre-allocated index 0347 used as instructed; did not self-scan ./tasks/.

## Step 2: Generate scaffold — 2026-06-14T00:00:00.000Z

Generated a complete **Expert-tier** scaffold for **Bicycle Shop Sales & Service**.

**Files written (all three):**
- `SCAFFOLD.yaml` — §1.0–§1.7, no design keys leaked
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Scaffold dimensions:**
- **Entities: 18** (Customer, Sku, TuneUpTier, ServiceBay, BayBooking, ServiceTicket, LaborLine, SalesOrder, OrderLine, Reservation, LayawayPlan, SpecialOrder, BuildJob, WarrantyClaim, TradeIn, RecallNotice, RecallAck, Payment)
- **Endpoints: 85** (includes one `/_clock/set_current_utc` test-driving endpoint)
- **Errors: 21**
- **Calculations: 9** (sku_available_units, order_total, ticket_quote, layaway_settlement, tradein_offer, build_fee, special_order_deposit, apply_store_credit, customer_open_recall_count)
- **State machines: 8** (ServiceTicket, SalesOrder, WarrantyClaim, BuildJob, SpecialOrder, LayawayPlan, TradeIn, BayBooking)

**Non-linear shapes (Expert "cycle or parallel" requirement, satisfied twice over):**
- **ServiceTicket has a cycle** — IN_PROGRESS ↔ AWAITING_APPROVAL revision loop (counted by `revision_count`)
- **SalesOrder has parallel dimensions** — independent `payment_status` × `fulfillment_status` axes
- WarrantyClaim adds a branching fork (UNDER_REVIEW → {APPROVED_REPAIR, APPROVED_REPLACE, DENIED})

**Difficulty design:** 9 rule_ids × 2 instances = **18 instances**, each grounded in §1.1–§1.7 with executable `setup_api_calls`/`trigger` chains and pre-computed literal asserts.

**Corner design:** 9 sections, **46 active instances + 3 `excluded_because` stubs**.

**Validation:** `scaffold_lint.py` returns `VERDICT: clean lint`. Entity (18) and endpoint (85) counts exceed Expert guideline bands (10–15 / 18–32) reflecting the scenario's eight distinct sub-domains; calcs (9), errors (21), state machines (8) at or above Expert band.

## Step 3: Copy INSTRUCTION.md — 2026-06-14T00:00:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-14T00:00:00.000Z

PRD written to `workspace/PRD.md` — **334 lines**.

**Sections covered:** §1 Introduction; §2 Global Specifications (RBAC/4 roles, §2.2 response envelope, pagination, common resource properties, nested-read resolution, reservation pool & stock reconciliation, OCC, monetary precision/rounding, cascades/compensation/recall safety); §3 Business Logic (12 subsections: catalog/customers/stock, cyclic service-ticket lifecycle, labor lines & rush pricing, bay bookings half-open intervals, parallel payment/fulfillment sales-order axes, payments & store-credit waterfall, layaway, special orders, parts-gated builds, branching warranty workflow, trade-ins/recalls, validation-priority ordering); §4 Endpoint Definitions (85 endpoints, 4-col); §5 Error Code Catalogue (21 codes, 2-col).

**Hard Contracts — all PASS:** Field-Name Coverage 74/74; Rule Coverage 20/20 spot-checks (OCC, 9 calcs, state machines, validation priority); §3 Path Purity 601 backtick tokens, 0 paths/methods. §2.2 byte-for-byte match.

**Confirmation:** Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read.

## Step 5: Generate unit tests — 2026-06-14T00:00:00.000Z

**Stage 1 — `test_helpers/` (9 files):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

**Stage 2 — `test_suite/` (conftest + 9 test files):** 82 test functions total. Queue A (Difficulty) = 36, Queue B (Corner) = 46. Instances skipped = 0 (all passed the PRD-first filter).

**Coverage audit (all passing):** All 18 difficulty instances ≥2 tests each; all 46 non-stub corner instances ≥1 test each; 3 `excluded_because` stubs correctly not translated. Every test carries exactly one `Design:` tag (82/82). No skip/xfail markers. All 102 PRD-quote citations verified verbatim.

## Step 6: Generate implementation — 2026-06-14T00:00:00.000Z

Generated Python + Flask implementation in `workspace/implementation/` (16 files): `start.sh`, `requirements.txt` (Flask 3.0.3), `app.py`, `db.py` (in-memory dicts), `errors.py` (21 errors), `response.py`, `middleware.py` (auth + RBAC), `helpers.py`, `services.py` (9 calcs + reservation/stock reconciliation + cascades), `routes/` (catalog/service/sales/holders/builds/misc).

**Endpoint count:** 85 (matches PRD §4 table). **Storage:** in-memory only (module-level dicts), no SQLite/JSON/tmp, no seeding. **start.sh:** reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec python3 app.py`.

## Step 7: Test & iterate loop — 2026-06-14T00:00:00.000Z

All 8 parallel rounds pass cleanly (79/79 each). Exiting with the Summary. (Orchestrator independently re-ran the 8-round sweep: rounds 1–8 all 79/79, 0 failed — results.{1..8}.json regenerated.)

**Iterations run:** 2 (initial diagnostic sweep + one fix sweep confirming clean).

**Diagnosis:** The initial 8-round sweep showed 3 consistently failing tests (failing 8/8 rounds each — no flakiness, a deterministic correctness issue). All three failed at the warranty-claim *submission* step: they submitted a claim against a RESERVED (non-delivered) sales order and expected HTTP 201, but the PRD-faithful implementation correctly returned 409 `ERR_NOT_PURCHASED`.

PRD §3.10 (verbatim, line 196): "At submission **and again at approval**, the system verifies purchase: the `source_order_line_id` must belong to a sales order whose fulfillment is `DELIVERED`... a claim that fails this referential check is rejected with `ERR_NOT_PURCHASED`." PRD §3.5 confirms a sales order can only be cancelled from PENDING/RESERVED and there is no transition out of DELIVERED. Therefore there is **no PRD-faithful path** to reach a claim in `UNDER_REVIEW` whose source order is non-delivered — the submission check blocks it, and a delivered order's status never reverts. The "approve fails / approve-priority on a non-delivered order" scenarios these three tests assert are unreachable under any PRD-faithful implementation.

**Tests deleted** (STEP 1b — not uniquely derivable / unreachable precondition; the only way to construct it violates the PRD's verbatim submission-time purchase check):
- `test_suite/test_02_state_machines_nonlinear.py::test_approve_rejected_when_source_order_not_delivered` — asserted submission against a reserved order succeeds (201) then approve fails; submission-time check makes this unreachable.
- `test_suite/test_04_validation_priority_and_boundaries.py::test_approve_not_purchased_beats_not_covered` — asserted P8-beats-P9 priority at *approve*, reachable only via a claim submitted against a non-delivered order (blocked at submission).
- `test_suite/test_04_validation_priority_and_boundaries.py::test_approve_not_purchased_status_409` — same unreachable precondition as above. (Its shared helper `_not_purchased_uncovered_claim` was removed too.)

The faithful positive counterpart `test_approve_succeeds_only_after_delivery` (delivered + covered → APPROVED_REPAIR) was kept and passes.

**Fixes applied to `test_helpers/`:** None — the helpers (`create_reserved_order`, `create_delivered_purchase`, `create_under_review_claim`) are PRD-faithful; the bug was in the test bodies/fixtures that submitted claims against non-delivered orders, and those scenarios have no faithful repair, so the tests were deleted rather than patched.

**Fixes applied to `implementation/`:** None — the implementation already enforces the purchase check at both submission (`routes/builds.py::create_warranty_claim`) and approval (`approve_warranty_claim`), exactly as PRD §3.10 requires. No PRD-required check was weakened.

Final state: 79/79 tests pass across all 8 parallel rounds.

## Step 8: Finalize PRD — 2026-06-14T00:00:00.000Z

**Line counts:** PRD.md = 334; PRD_FINALIZED.md = 334. **%-delta: 0.00%** (byte-identical, both 54120 bytes).

**Changes:** **NO CHANGES — byte-identical copy.** The sole `<step_7_diff>` item was 3 test deletions (unreachable precondition: warranty claim submitted against a non-DELIVERED order) with 0 implementation fixes and 0 test_helpers fixes. The PRD already uniquely determines the implementation's behavior: §3.10 submission-and-approval purchase check (DELIVERED-only + matching customer_id → else `ERR_NOT_PURCHASED`); §3.5 no transition out of DELIVERED; §3.12 purchase-before-coverage (P8 before P9) ordering. Per method, no edits were invented to justify the step.

**Pre-edit search log (enumeration leading to "no edits"):** Subject A warranty purchase check — enumerated `routes/builds.py::_purchase_check`/`create_warranty_claim`/`approve_warranty_claim`/`resolve_warranty_claim`; matches PRD §3.10 verbatim. Subject B sales-order fulfillment SM — enumerated `routes/sales.py` reserve/deliver/cancel; no exit from DELIVERED, matches §3.5. Subject C approve-time ordering — enumerated `approve_warranty_claim` state→purchase→coverage→replace ordering; matches §3.12/§3.10. Cross-check warranty close (§3.2) `routes/service.py::close_ticket` APPROVED_REPAIR→RESOLVED consistent.

## Step 9: Complete PRD — 2026-06-14T00:00:00.000Z

**Source vs. output:** PRD_FINALIZED.md = 334 lines / 54,120 chars; PRD_COMPLETED.md = 334 lines / 54,972 chars. Char delta **+852** (all edits in-paragraph).

**Counts:** 2 mismatch-revisions, 3 ambiguity-pins (5 edits total).

**Changes:**
- §2.4 — revise — mismatch — "Four entities are append-only/ledger-style" → "Three" (only `RecallNotice`, `RecallAck`, `Payment` are ledger via `stamp_create(ledger=True)`); clarified `Reservation` is a full entity with `updated_at`/`version` bumped on commit/release — helpers.py:13-21, services.py:50-63.
- §2.6 — insert — ambiguity — pinned SKU `available` computed field = `on_hand` − `reserved`, not floored at zero — routes/catalog.py:86, services.py:14-21.
- §2.7 — insert — ambiguity — pinned order's "primary `Sku`" = SKU of earliest-created order line; missing/non-integer `expected_sku_version` → `ERR_INVALID_REQUEST` — routes/sales.py:72,80-81.
- §3.9 — insert — ambiguity — pinned build part/frame reservations are NOT gated on availability or MANDATORY recall (unlike sales/layaway/special-order), so `available` may go zero/negative; frame reservation quantity = 1 — routes/builds.py:80,97.
- §4 — revise — mismatch — "All endpoints mounted under `/shop`" → clock endpoint is the sole exception at `/_clock/set_current_utc` (no `/shop` prefix) — routes/misc.py:193.

**Pipeline complete.** Final state: 79/79 tests pass across all 8 parallel rounds; PRD_COMPLETED.md is the finished contract.
