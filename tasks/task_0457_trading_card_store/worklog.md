# Worklog — task_0457_trading_card_store

## Step 1: Create task directory — 2026-06-21T11:56:51.000Z

Created `tasks/task_0457_trading_card_store/` and `tasks/task_0457_trading_card_store/workspace/` (fixed directory; index-scan skipped per orchestrator instructions). Scenario: Trading Card & Hobby Game Store. Difficulty target: Expert (10-15 entities).

## Step 2: Generate scaffold (Expert) — 2026-06-21T12:15:03.000Z

All three files are written. There's a pre-existing `worklog.md` and `workspace/` dir in the directory (not created by me). The three required scaffold artifacts are complete and the lint passes clean.

## Summary

Generated the Expert-tier scaffold for **task_0457_trading_card_store** (Trading Card & Hobby Game Store). All three files written and validated:

- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

**Entity count: 12** — Customer, InventoryItem, BuylistSubmission, BuylistLine, ReleaseProduct, PreOrder, Event, Registration, Pairing, GradingSubmission, ConsignmentCase, StoreCreditLedger (the last is an append-only event log with `common_fields: false`).

**State machines: 7** (with non-linear shapes per Expert band):
- Event — **cyclic** (IN_PROGRESS→IN_PROGRESS pairing-round self-loop) + terminal cancel cascade
- Registration — **parallel dimensions** (payment_status × checkin_status evolve independently)
- GradingSubmission — **branching fork-join** (AT_GRADER → GRADED | REJECTED with divergent side effects)
- BuylistSubmission — accept/reject + compensating void
- PreOrder — allocation lifecycle (OCC-guarded, guarded by ReleaseProduct state)
- Pairing — result reporting (guarded by Event state)
- ConsignmentCase — sale + settlement

**Counts:** 9 calculations, 16 validations (priority-ordered), 64 endpoints (38 POST / 26 GET), 22 errors, 1 concurrency rule (OCC on `ReleaseProduct.version` for pre-order allocation), 3 roles (Customer = entity_backed; StoreManager + JudgeStaff = opaque).

**Difficulty design:** all 9 §0.5 rules covered with exactly 2 instances each (18 total).

**Corner design:** 33 active instances + 3 `excluded_because:` stubs.

**Validation:** `scaffold_lint.py` returns `VERDICT: clean lint`. One enum dead-end (`ReleaseProduct.DISCONTINUED`) was removed during the self-consistency audit.

Note: endpoint count (64) exceeds the Expert 20-32 guideline, but every endpoint is load-bearing (single-resource GETs for collection-segment derivation, filtered-list/sub-resource GETs for FK reverse-reachability, every POST maps to a declared state transition or creation).

## Step 3: Copy INSTRUCTION.md — 2026-06-21T12:15:03.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-21T12:21:04.000Z

**Output:** `workspace/PRD.md` (~300 lines, ~43.7 KB)

### Section structure
- §1. Introduction
- §2. Global Specifications & System-Wide Principles — 9 subsections (RBAC; API Response Structure; Pagination; Resource Topology; Common Resource Properties incl. StoreCreditLedger exception; Monetary/Rounding/Integer counts round-half-up; OCC on Release Allocation; Store Credit as Settlement Ledger; Validation Ordering priority 1–16)
- §3. Business Logic & Workflows — 8 lifecycle-grouped subsections
- §4. Endpoint Definitions — 4-column table, all 67 endpoints
- §5. Error Code Catalogue — 22 errors

### Hard Contract reports
- Field coverage: 56/56 entity fields, 36/36 request bodies, 14/14 query params — PASS
- Rule coverage: 16/16 validations, 1/1 OCC, 7/7 state machines, 9/9 calculations, cascades expressed — PASS
- Path purity (§3): 340 backtick tokens scanned, 0 path/method tokens — PASS

### Confirmation
Neither withheld design file (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) was read, opened, grepped, or referenced.

## Step 5: Generate unit tests — 2026-06-21T12:37:22.000Z

**Test infrastructure (`test_helpers/` — 9 files):** __init__.py, types.py, api_client.py, api_errors.py (22 errors), assertions.py (per-entity + invariant guards), factories.py, constants.py, test_users.py (opaque-role shared headers + make_customer_headers), fixtures.py (composite setup tiers).

**Test suite (`test_suite/` — conftest + 11 test files, 69 tests):**
- Queue A (Difficulty): 18/18 instances translated, 0 skipped — exactly 2 tests each (36 tests).
- Queue B (Corner): 33/33 non-stub instances translated, 0 skipped. 3 `excluded_because:` stubs correctly NOT translated.

**Audit:** 69 tests, 69 Design tags (one verbatim Design: line each, all resolve to real instances). No skip/skipif/xfail. All PRD citations verbatim + rule-bearing; all imports resolve; all 21 files compile. No instances skipped — every design-index instance passed the PRD-first two-condition filter.

## Step 6: Generate implementation — 2026-06-21T12:37:22.000Z

Generated complete Python + Flask implementation at `workspace/implementation/`.

**Files:** start.sh (executable, foreground, guarded pip install), requirements.txt (flask==3.0.3), app.py (entry + all 60+ routes, error handlers, validation/state-machine/RBAC), db.py (in-memory dicts + UUID/timestamp/logical-clock helpers), errors.py (ApiError + §5 catalog), response.py (envelope helpers), common.py (auth, common-field stamping, body parsing, pagination), calculations.py (round-half-up money rules), services.py (lookups, append-only ledger, balance/lifetime-spend/tier reconciliation).

**Launch:** Flask `app.run(host="0.0.0.0", port=int(os.environ.get("PORT","10000")), threaded=True)`. start.sh: cd to dir, guard install, `exec python3 app.py`.

**Constraints confirmed:** in-memory only (module-level dicts, no SQLite/file/JSON/tmp); no startup seeding; start.sh reads $PORT, binds 0.0.0.0, runs foreground via exec.

**Smoke tests (0 failures):** buylist 70% valuation + cascade + ledger; early-bird final fee (900) vs provisional (1000); pre-order priority (28); OCC stale-version 412; allocation-exceeded 409; consignment payout per-unit rounding (2550); grading fee (2400) + GRADED/REJECTED fork; cancel-event depth-3 cascade net-zero refund; schedule conflict half-open overlap; venue overlap (5+5>8); 401/403 auth; pagination envelope.

**PRD-fidelity note from impl-gen:** `/events/{id}/wpn-report` is declared in PRD §4 + §3.5 but not in the truncated SCAFFOLD §1.5 range the subagent read directly; implemented per PRD (PRD wins).

## Step 7: Run tests and iterate — 2026-06-21T12:52:20.000Z

All clean. The loop is complete — two consecutive 8-round parallel sweeps passed with 68/68 in every round.

## Summary

**Iterations run:** 3 sweeps. Baseline sweep surfaced 3 union failures; after fixes, two consecutive confirmatory 8-round sweeps were fully green (68/68 × 16 round-runs).

**Tests deleted (1):**
- `test_pay_then_withdraw_checked_in_refunds_charged_fee` in `test_suite/test_06_difficulty_complements.py` — **STEP 1b non-unique-derivability / BRANCH-ASYMMETRIC SIDE EFFECT**. PRD §3.4 defines withdraw verbatim as "moves `checkin_status` from `PENDING` to `WITHDRAWN`" (a single-source-state transition). A faithful PRD-only implementer defines withdraw only from `PENDING`, so direct withdrawal of a `CHECKED_IN` registration correctly returns `ERR_INVALID_STATE` (which is exactly what the implementation did, tripping the test's expected-200). The refund clause's "if the registration was checked in → `charged_fee_cents`" branch is still genuinely reachable via the §3.5 event-cancel cascade (which withdraws + refunds `CHECKED_IN` registrations), so the cited refund sentence does not uniquely determine that *direct* withdrawal of a `CHECKED_IN` registration succeeds. Two divergent PRD-faithful implementations exist; per the cardinal rule, deleted. The sibling `test_pay_then_withdraw_conserves_store_credit` (withdraw from PENDING → refund `quoted_fee_cents`) and the cancel-cascade refund tests still cover the refund paths. Scaffold rule that drove generation: `Difficulty/compensating_invariant/registration_pay_refund_conserves_store_credit`.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/ (`app.py` only):**
1. Patched `socket.getfqdn` to a constant at module top, before Flask/Werkzeug import. Root cause of the deterministic "API server could not be restarted" setup errors: Werkzeug's dev server resolves the host FQDN at startup, and `socket.getfqdn()` stalled ~5s per boot on this host (mDNS `.local` reverse resolution). Under per-test-server isolation × 8 concurrent rounds, the 5s-per-boot stall pushed some boots past the runner's readiness window. Boot dropped from ~5.25s to ~0.23s under 8x load.
2. Replaced `app.run()` with `_serve()` using `werkzeug.serving.make_server` inside a ~20s bind-retry loop. When 8 rounds concurrently kill-and-respawn servers before every test, the just-killed listener's port can be briefly held, and a one-shot bind would crash with `EADDRINUSE` (surfacing as "could not be restarted", deterministically on the first restart/test #2). Retrying the bind lets the new server reliably claim the port. Verified with 48 concurrent restarts: 0 failures.

Both implementation fixes are infrastructure-robustness only (no endpoint/field/side-effect added or removed); no PRD-required check was weakened. Storage remains in-memory only.

**Orchestrator note:** Test count after deletion = 68 (verified via Design: tag count). results.{1..8}.json were cleaned between sweeps by the loop's `rm -f`; final state confirmed green by the subagent's two confirmatory sweeps.

## Step 8: Finalize PRD — 2026-06-21T12:56:06.000Z

The patch is exactly one paragraph changed (line 167), everything else verbatim. The edit is a minimal, targeted pin.

## Summary

**Line counts:** PRD.md = 299 lines, PRD_FINALIZED.md = 299 lines. 0% line-count delta (single paragraph revised in place). Exactly one paragraph (§3.4, line 167) differs; all other 298 lines verbatim.

**Changes (one bullet):**
- **§3.4 (Events, Registration) — revise — Pinned that direct withdrawal is defined *only* from `checkin_status == PENDING` (a `CHECKED_IN` registration is rejected with `ERR_INVALID_STATE`), and clarified that the refund's `charged_fee_cents` ("if checked in") branch is reachable only via the §3.5 event-cancel cascade, never via direct withdrawal — `implementation/app.py:1038` (withdraw guard) and `app.py:880-882` (`_refund_registration` branch).**

**Per-edit pre-edit search log:**
- (a) Subject: source-state of direct withdraw action + refund-amount branch (charged_fee_cents vs quoted_fee_cents).
- (b) Impl paths enumerated: withdraw_registration (app.py:1030-1047), _refund_registration (app.py:880-886), cancel_event cascade (app.py:889-910), check_in_registration (app.py:1001-1027), pay_registration (app.py:986-997), registration creation (app.py:961-963); grep of all _refund_registration/EVENT_REFUND/charged_fee_cents/quoted_fee_cents callsites confirmed exactly two refund callsites (909 cascade, 1046 withdraw).
- (c) Wording adjustment: Scoped the PENDING-only restriction to "direct withdrawal" (customer action) so it does not contradict the §3.5 cancel cascade (which legitimately drives CHECKED_IN→WITHDRAWN). Left the refund-amount branch sentence intact since _refund_registration is shared and the charged_fee_cents branch is reachable via the cascade. Added explanatory clause tying the checked-in branch to the cascade.

**Infrastructure items:** The two app.py fixes (socket.getfqdn patch; _serve() bind-retry loop) are pure server boot/bind robustness changes; correctly required no PRD edit. The deleted test is the sole behavioral pin.

## Step 9: Complete PRD — 2026-06-21T13:02:23.000Z

All six edits in place, each an in-paragraph insert/revision with no new sections or lines. Line count unchanged (299), char delta +1238.

## Summary

**File comparison**
- `PRD_FINALIZED.md`: 299 lines, 44,278 chars
- `PRD_COMPLETED.md`: 299 lines, 45,516 chars (char delta: +1,238; line count unchanged — all edits in-paragraph)

**Change counts**: 6 total — 4 ambiguity-pins, 2 mismatch-revisions

**Per-change log**
- §2.3 Pagination — insert — ambiguity — pinned that out-of-range/non-integer `limit`/`offset` are silently coerced (limit clamped to [1,100], negative offset → 0, unparseable → default) rather than rejected — `common.py:153-172`
- §2.5 Common Resource Properties — insert — ambiguity — pinned `version`'s initial value as `1` — `common.py:56`
- §3.1 Customers — revise — mismatch — impl also rejects banned customers at registration with `ERR_CUSTOMER_BANNED`, after existence and before schedule-conflict/event-full — `app.py:932-934`
- §3.5 Tournament Floor (venue check) — revise — mismatch — impl only counts events in `OPEN`/`IN_PROGRESS` and excludes `SCHEDULED`/`COMPLETE`/`CANCELLED` — `app.py:818`
- §3.5 Tournament Floor (pairing creation) — insert — ambiguity — pinned that creating a pairing requires the parent event to be `IN_PROGRESS`, else `ERR_INVALID_STATE` — `app.py:1067-1068`
- §3.5 Tournament Floor (WPN report) — insert — ambiguity — pinned that the report is not gated on event state (readable any time), rows are the event's registration objects, response is a paginated list with standard meta — `app.py:777-788`

**Notes on items left unchanged**: defensive non-negative bound checks (e.g. `market_price_cents >= 0` → `ERR_INVALID_REQUEST`) consistent with PRD well-formedness stage; buylist-line add has no DRAFT precondition and PRD makes no contrary claim; fulfill remaining-balance, early-bird boundary (<=), pay-WITHDRAWN ordering, refund branches, and all calculation rounding orders already matched impl uniquely.

---

# Pipeline complete

All 9 steps finished. Final state:
- Scaffold (Expert, 12 entities) + 2 design indices
- PRD.md → PRD_FINALIZED.md (1 pin) → PRD_COMPLETED.md (6 edits)
- 68 tests (1 deleted in Step 7), all green across two confirmatory 8-round parallel sweeps
- Working Python/Flask implementation (in-memory, per-test-server safe)
