# Worklog — task_0606_device_protection_insurance

## Step 1: Create task directory — 2026-06-21T12:36:00.000Z

Created `tasks/task_0606_device_protection_insurance/` with `workspace/` subdirectory (pre-assigned index, no scan). Verified `INSTRUCTION.md` present at project root.

## Step 2: Generate scaffold (Expert) — 2026-06-21T12:58:00.000Z

Generated all three scaffold artifacts for **task_0606_device_protection_insurance** (Asurion-style Device Protection & Mobile Insurance Claims) at the **Expert** difficulty band. `scaffold_lint.py` returns **VERDICT: clean lint** (43 endpoints, 10 entities, 489 §1.8+§1.9 calls scanned, 0 violations), and an independent grounds/uniqueness/excluded-ref check passes.

**Files written:** SCAFFOLD.yaml (900 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1243 lines), SCAFFOLD_CORNER_DESIGN.yaml (1371 lines).

**Design profile:** ledger-reconciliation primary (depreciated book value vs flat replacement cap) blended with workflow-orchestration (claim lifecycle + repair-vs-replace routing + advanced-exchange/trade-in logistics); flat topology, branching state-machine shape, peer-roles, immediate consistency.

**Scaffold contents (§1.1–§1.7):**
- **Entities: 10** — Customer, Plan, ReplacementSku, Enrollment, PremiumInvoice, Claim, FraudScreen, RepairOrder, AdvancedExchange, TradeIn (11 FKs, all with reverse-reachability GETs).
- **State machines: 4** — Enrollment (revert loop ACTIVE↔SUSPENDED + cancel cascade), Claim (branching fork APPROVED→ROUTED_REPAIR/ROUTED_REPLACE rejoining at FULFILLED), AdvancedExchange (clock-swept RETURN_DUE + compensating cancel), TradeIn (credit/recycle/e-waste with fee reversal). Plus 2 concurrency rules (OCC on Enrollment.version for approve, on Claim.version for ship).
- **Calculations: 5** — quote_deductible, replacement_value (dual-variant book-value vs capped, floor/cap nesting), fraud_velocity (windowed → PASS/REVIEW/BLOCK), tradein_credit (tiered by grade), nonreturn_fee.
- **Validations: 17** (ordered, priority 1–17). **Endpoints: 43** (incl. `/_clock/set_current_utc` default 2026-01-01T00:00:00Z and `/_clock/run_return_sweep`). **Errors: 20. Roles: 4** — PlatformAdmin, Subscriber (entity_backed:Customer), ClaimsAdjuster, LogisticsAgent.

**Difficulty design (§1.8):** 9 rules × 2 instances = 18 instances with executable setup chains and pre-computed literal asserts. **Corner design (§1.9):** 8 sections, 30 active instances + 4 `excluded_because` stubs.

## Step 3: Copy INSTRUCTION.md — 2026-06-21T12:59:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-21T13:03:00.000Z

Generated `workspace/PRD.md` (~298 lines, 38511 bytes) for the Device Protection Insurance API.

**Structure:** 5 top-level sections (Introduction, Global Specifications, Business Logic & Workflows, Endpoint Definitions, Error Code Catalogue), 21 subsections. §2 has 9 domain subsections (RBAC, fixed response structure, pagination, common properties + logical clock, OCC, hierarchical cascades, left-to-right resolution, monetary precision, fraud posture). §3 has 12 lifecycle subsections.

**Hard Contracts — all PASS:** (1) Field-Name Coverage: all 51 scaffold field names + request/query/path identifiers verbatim, 0 missing. (2) Rule Coverage: both OCC rules, all 4 calculations with constants embedded, all state transitions/cascades/priority-ordered gate/grade-path exclusivity. (3) §3 Path Purity: 369 backtick tokens, 0 paths/bare methods/method+path combos.

**Confirmation:** difficulty/corner design files NOT read.

## Step 5: Generate unit tests — 2026-06-21T13:13:00.000Z

Generated test infrastructure under a strict design-index-only contract. **test_helpers/ (9 modules):** types.py, api_client.py (43 endpoint methods), api_errors.py, assertions.py, factories.py, constants.py, test_users.py (opaque-role headers + entity_backed Subscriber builder), fixtures.py, __init__.py. **test_suite/ (8 files, 66 test functions):** test_01 reference/enrollment, test_02 enrollment lifecycle, test_03 claim filing & screening, test_04 adjudication, test_05 routing & replacement, test_06 fulfillment & trade-ins, test_07 RBAC & auth.

**Coverage:** All 18 Difficulty instances (queue A) covered by ≥2 tests; all 30 non-stub Corner instances (queue B) by ≥1. Every test carries verbatim PRD citation + one `Design:` tag. The 4 `excluded_because:` Corner stubs correctly NOT translated.

**PRD-fidelity correction:** `tradein_credit_reverses_nonreturn_fee_depth2` reordered (sweep first w/o trade-in → fee assessed/RETURN_DUE → late trade-in → credit reverses fee → DELIVERED) per PRD §3.11 ("fee only when no trade-in exists"). All files byte-compile, 66 tests collect, no skip/xfail.

## Step 6: Generate implementation — 2026-06-21T13:13:00.000Z

Built Python + Flask implementation in `workspace/implementation/`. **Files (12):** start.sh (guarded-install foreground launcher), requirements.txt (Flask 3.0.3), app.py, clock.py (logical clock default 2026-01-01T00:00:00Z), errors.py (20 error IDs), db.py (in-memory dicts only, no seeding), response.py (envelope + pagination), middleware.py (X-User-ID/Role auth + RBAC), calculations.py (Decimal ROUND_HALF_UP), helpers.py, routes/{reference,enrollments,claims,logistics}.py.

**Endpoints implemented: 45** (all PRD §4 / scaffold §1.5 routes). Verified live: auth 401, RBAC 403, ownership errors, IMEI Luhn/duplicate, full REPLACE + REPAIR branches, OCC stale-version 412, return sweep + non-return fee + late-trade-in reversal, pagination bounds, fraud velocity, clock-set. **start.sh:** reads $PORT (default 10000), binds 0.0.0.0, foreground via `exec python3 app.py`, guarded pip install.

## Step 7: Test and iterate to PASS — 2026-06-21T13:30:00.000Z

Clean 8-round parallel sweep: all 8 rounds pass 61/61.

**Iterations run:** 3 sweeps (1 initial diagnostic + 2 single-round verifications) plus the final 8-round parallel stability sweep. Final 8-round sweep passed 61/61 in every round.

**Root cause:** Dominant failure (46 of 66 tests in initial sweep) was a single test-helper timing bug — `create_active_enrollment` activated enrollments at clock `2026-06-01` (so `enrolled_at = 2026-06-01`), then filed claims with `incident_at` between March–May, which a PRD-faithful implementation correctly rejected with `ERR_INCIDENT_OUT_OF_WINDOW` (PRD 3.4: incident must be strictly after `enrolled_at`). Implementation correct; fixture wrong.

**Tests deleted (4):**
- `test_duplicate_premium_invoice_cycle_rejected` (test_02) — PRD SILENCE. PRD 3.3 never states a second invoice for existing `(enrollment_id, cycle_index)` is rejected; the `ERR_INVALID_STATE` uniqueness rule exists only in SCAFFOLD_DIFFICULTY_DESIGN.yaml (resource_temporal_overlap). Scaffold-only.
- `test_screen_requires_active_enrollment` + `test_screen_blocked_when_enrollment_suspended_unchanged_claim` (test_03) — UNCONSTRUCTABLE PRECONDITION (STEP 1b). Both suspend an enrollment holding an open claim, but PRD 3.2 permits suspension "only when `open_claim_id` is null." Needs a non-ACTIVE enrollment with an open claim — unreachable by any legal transition.
- `test_enrollment_not_active_beats_open_claim` + `test_not_active_check_leaves_existing_open_claim_intact` (test_04) — same unconstructable suspend-with-open-claim precondition.

**Fixes applied to test_helpers/ (`fixtures.py`, `constants.py`):**
- constants.py: added `ENROLL_CLOCK = "2026-01-15T00:00:00Z"` (after device purchase, before earliest incident).
- create_active_enrollment: brackets activation at `ENROLL_CLOCK` then restores clock to `CLOCK_DEFAULT` — core fix.
- create_plan: defaults to fresh unique `code` per call (PRD 3.1 plan-code uniqueness).
- create_active_enrollment IMEI: defaults to fresh Luhn-valid unique IMEI (`fresh_imei`) for multi-enrollment tests; duplicate-IMEI tests still pass `imei` explicitly.
- Added `pay_through_current_cycle(enr)` computing current billing cycle from `enrolled_at` vs clock for reinstatement tests (PRD 3.2 premium_paid_through_cycle precondition).

**Fixes applied to test_suite/:**
- test_02: two reinstatement tests use `pay_through_current_cycle` instead of hard-coded cycle 0.
- test_04 `_raise_to_watch`: moved two denied incidents to `2026-01-20`/`2026-02-10` so they age out of the THEFT claim's 90-day velocity window (THEFT screens at velocity 1 → PASS, customer stays WATCH) instead of velocity 3 → BLOCK.
- test_06: 5 `create_trade_in` calls corrected to expect HTTP 201 (POST /trade-ins creates) instead of default 200.
- test_07 `test_subscriber_cannot_withdraw_other_customers_claim`: brackets manual activation at `ENROLL_CLOCK`.

**Fixes applied to implementation/:** None — implementation was PRD-faithful; every failure traced to test-helper preconditions, test expectations, or scaffold-only assertions.

## Step 8: Finalize PRD — 2026-06-21T13:35:00.000Z

Created `workspace/PRD_FINALIZED.md`. Line counts: PRD.md = 298, PRD_FINALIZED.md = 298 (one line revised in place, ~0.3% char delta).

**Changes (1 edit):**
- §3.2 Enrollment Lifecycle (Reinstatement) — revise — Pinned how the "current cycle" index is derived (floor of whole 30-day periods since `enrolled_at`, clamped ≥0, 0 when `enrolled_at` null), the `premium_paid_through_cycle >= current_cycle` comparison, and `ERR_INVALID_STATE` on unmet precondition — `implementation/routes/enrollments.py:136-141` + `:145-151`.

**No-edit items:** duplicate premium invoice (PRD silence, impl performs no uniqueness check — faithful by omission); suspend-with-open-claim deletions (unconstructable, no reachable behavior); trade-in 201 (PRD §4 already pins 201); velocity-window/ENROLL_CLOCK fixes (PRD §3.4/§3.5 already pin behavior).

## Step 9: Complete PRD — 2026-06-21T13:36:00.000Z

Created `workspace/PRD_COMPLETED.md` from PRD_FINALIZED.md. Lines: 298 → 298 (all in-paragraph). Chars: 39,041 → 40,266 (+1,225). **Counts:** ambiguity-pins 6, mismatch-revisions 2.

**Changes (8):**
- §2.3 Pagination — insert — ambiguity — `created_at` ties break by ascending creation order — `helpers.py:78-79`.
- §3.1 Reference (customer) — insert — ambiguity — duplicate `carrier_account_number` rejected with `ERR_VALIDATION` — `routes/reference.py:46-48`.
- §3.1 Reference (plan) — insert — ambiguity — duplicate plan `code` rejected with `ERR_VALIDATION` — `routes/reference.py:78-80`.
- §3.6 Adjudication (approval) — insert — ambiguity — annual-limit tally statuses + `incident_at` ≥ clock−365d — `routes/claims.py:30-42`.
- §3.6 Adjudication (denial) — revise — mismatch — denial_reason outside valid set also rejected `ERR_VALIDATION` — `routes/claims.py:312-314`.
- §3.7 Routing — revise — mismatch — non-integer `repair_cost_cents` → `ERR_ROUTE_INPUT_MISSING`, negative → `ERR_VALIDATION` — `routes/claims.py:250-253`.
- §3.4 Filing — insert — ambiguity — submission-check order (ACTIVE → incident window → theft police report → open-claim) — `routes/claims.py:65-85`.
- §3.11 Return Sweep — insert — ambiguity — `200 OK` envelope with `data.swept_exchange_ids` array — `routes/logistics.py:337`.
- §3.8 Replacement Value — insert — ambiguity — device age in months clamped ≥0 — `calculations.py:46-48`.

## Pipeline complete — 2026-06-21T13:37:00.000Z

Final 8-round parallel stability sweep: all 8 rounds pass **61/61**. results.{1..8}.json persisted in `workspace/implementation/`. All pipeline artifacts present.
