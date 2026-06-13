# Worklog — task_0294_formalwear_costume_rental

## Step 1: Create task directory — 2026-06-11T02:28:18.000Z

Created `tasks/task_0294_formalwear_costume_rental/` and `tasks/task_0294_formalwear_costume_rental/workspace/` (pre-assigned task directory; no index scan performed).

## Step 2: Generate scaffold (Expert) — 2026-06-11T02:58:02.000Z

All three scaffold artifacts are complete and lint-clean. Final summary from scaffold-generator subagent:

Generated the three required scaffold artifacts for **task_0294_formalwear_costume_rental** at the **Expert** difficulty band. The scaffold was built purely from the scenario description and the generator skill spec (no sibling tasks consulted). Final `scaffold_lint.py` verdict: **clean lint** (361 §1.8/§1.9 calls validated against §1.5; all 11 FKs reverse-reachable).

**Files**
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Complexity profile:** quota_allocation × temporal_windowing; flat topology; branching state-machine shape; peer_roles; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation. `api_prefix: /` (flat peer entities at the API root — required for the linter's segment derivation to work on a flat topology).

**Scaffold contents**
- **10 entities:** Catalog, GarmentUnit, Customer, MeasurementProfile, Reservation, Alteration, PartyOrder, Settlement, LedgerEntry (append-only), FitCheck.
- **4 state machines:** Reservation (branching fork-join PICKED_UP→{RETURNED|OVERDUE}→SETTLED, 7 states), GarmentUnit (cyclic AVAILABLE↔RESERVED + IN_CLEANING/RETIRED), PartyOrder (compound posture FORMING↔READY→LOCKED/DISSOLVED), Alteration. Plus 2 OCC concurrency rules on PartyOrder.version (member-confirm + lock).
- **7 calculations:** unit_selection, booking_quote (tiered, pinned round-per-day-first), settlement_charges (nested min/max + waterfall), deposit_conservation, party_posture, recommended_size, fit_verdict.
- **14 validations** (priority-ordered), **41 endpoints** (incl. reverse-reachability GETs + `/_clock/set` & `/_clock/advance` test-driving endpoints), **15 errors**, **3 roles** (Customer entity_backed; StoreClerk/StoreManager opaque).

**Difficulty design:** 9 §0.5 rules × 2 instances = **18 instances**, each with executable empty-DB setup chains and code-computed literal asserts. **Corner design:** **37 instances** (29 active + 8 excluded_because stubs).

## Step 3: Copy INSTRUCTION.md — 2026-06-11T02:58:02.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0294_formalwear_costume_rental/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-11T03:03:22.000Z

Generated `workspace/PRD.md` — **250 lines** — from the formalwear-costume-rental scaffold (SCAFFOLD.yaml only; both design files withheld).

**Sections covered:** §1 Introduction; §2 Global Specs (10 subsections: RBAC, §2.2 envelope, pagination, common resource props incl. LedgerEntry common_fields:false, nested-reference validation, validation ordering, monetary precision/rounding, inventory lifecycle, deposit ledger/conservation invariant, OCC); §3 Business Logic (10 lifecycle subsections); §4 41-endpoint table + filter params; §5 15-error catalogue.

**Hard Contracts — all PASS:** Contract 1 field coverage 64/64; Contract 2 rule coverage (both OCC rules with expected_*_version + ERR_STALE_VERSION + HTTP 412; tiered pricing 1.00/0.90/0.80, damage 60%, waiver cap 30000, MAX_STRIKES 2, size-chart boundaries, fit ordinals; validation priority order; all error triggers); Contract 3 §3 path-purity (382 backtick tokens, zero path/method violations).

**Notable decisions:** pinned rounding order in booking_quote (round per-day effective rate first, then × rental_days); damage-fee min()-after-rounding; OVERDUE branch asymmetry (sweep flags OVERDUE, no settlement, unit stays OUT vs clerk return creating settlement); constants embedded with unit context.

## Step 5: Generate unit tests — 2026-06-11T03:22:16.000Z

Generated `test_helpers/` (9 files) + `test_suite/` (conftest + 13 test files, **65 tests**). 65 tests collect cleanly; every test carries a verbatim ≥8-word PRD citation plus exactly one `Design:` tag.

**Coverage (complete, audited):** Queue A (Difficulty) all 18 instances × 2 tests = 36 tests; Queue B (Corner) all 29 non-stub instances ≥1 test = 29 tests; 8 corner stubs not translated (each cites a difficulty instance that owns the assertion — all cross-refs resolve); **0 instances skipped** (every instance passed the PRD-first two-condition filter, incl. the two validation-priority orderings stated in §2.6/§3.6).

**Validation passed:** exactly one verbatim Design tag per test (no untagged/dual-tagged/stub-tagged); every docstring citation survives literal whitespace-collapsed grep of PRD.md; no skip/skipif/xfail; no scaffold refs; all imports resolve; all 65 collect under pytest with zero errors.

## Step 6: Generate implementation — 2026-06-11T03:22:16.000Z

Generated Python + Flask implementation in `workspace/implementation/` (**26 files**). **41 endpoints**, matching PRD §4 / scaffold §1.5 exactly. start.sh: guarded-install foreground launcher (`exec python3 app.py`, reads `$PORT` default 10000, binds `0.0.0.0`).

**Files:** start.sh, requirements.txt (flask==3.0.3), app.py, clock.py (logical system clock), db.py (in-memory dicts), errors.py/response.py/middleware.py, routes/ (10 files), services/ (calculations, ledger, views, helpers, party, reservation_ops).

**Notable decisions:** logical clock drives all timestamps (created_at = sweep/window key + tie-break with monotone insertion sequence); computed fields derived on read, never stored (catalog active_unit_count; customer deposit_held_cents/balance_owed_cents/open_strike_count from ledger; party confirmed_member_count/posture — posture stores only sticky LOCKED/DISSOLVED, READY/FORMING flip from count threshold); decimal.Decimal + ROUND_HALF_UP for money, rounding-order pinned (per-day rate first, then ×days; damage min() after rounding); validation precedence per §2.6 (auth → role FORBIDDEN → existence 404 → ownership FORBIDDEN → well-formedness → window → state → business rules); no seeding (empty store on boot, verified).

**Verification:** end-to-end smoke through `bash start.sh` — full happy path with deposit conservation, late+DAMAGED settlement, overdue clock sweep, party OCC, pickup gating precedence, clear-cleaning/retire OCC, error-code precedence. start.sh boots cleanly, no tracebacks/500s/disk persistence.

## Step 7: Test & iterate loop — 2026-06-11T03:27:49.000Z

Final 8-round parallel sweep: all 8 rounds `passed=65 / total=65`, zero failures/errors/skips.

**Iterations run:** 2 (initial sweep → diagnose+fix → confirming sweep).

The first 8-round sweep surfaced exactly one consistent failure: `test_03_boundaries.py::test_late_fee_two_days_routes_overdue`. It asserted that a clerk-driven *late* return executed while the reservation is still `PICKED_UP` leaves the reservation in `OVERDUE`; the implementation was returning `SETTLED`.

**Diagnosis (full protocol):**
- STEP 1 (coverage + unique-derivability): PRD covers and uniquely determines the outcome. §3.7 scopes the `SETTLED` outcome to the *already-OVERDUE* case; §3.8 ("a settlement reached on the late branch may leave the reservation in `OVERDUE`" and "Finalization is permitted only when a Settlement exists … and the reservation is in `RETURNED` or `OVERDUE`") requires a late return from `PICKED_UP` to leave the reservation in `OVERDUE`. Uniquely derivable; test kept.
- STEP 2 (test-vs-PRD consistency): fixture `create_picked_up_reservation` + `return_reservation` faithful to PRD. No test/helper bug.
- STEP 3: confirmed implementation bug.

**Tests deleted:** none.
**Fixes applied to test_helpers/:** none.
**Fixes applied to test_suite/:** none.
**Fixes applied to implementation/:** `workspace/implementation/services/reservation_ops.py`, function `record_return`: captured the reservation's `prior_status` before mutation and changed the late-branch routing to route by entry state — on-time → `RETURNED`; late return from `PICKED_UP` → `OVERDUE` (awaiting finalize); return while already `OVERDUE` (sweep-flagged) → `SETTLED`. Previously the late branch unconditionally set `SETTLED`. `/settlements/{id}/finalize` already accepted both `RETURNED` and `OVERDUE`, and `deposit_held_cents` is ledger-derived, so no other path changed.

Note: runner results-file fields are `passed`/`total`/`failed`/`errors`/`skipped` top-level and `status` per-test.

## Step 8: Finalize PRD — 2026-06-11T03:29:45.000Z

`PRD_FINALIZED.md` created as a copy of `PRD.md` but **required no edits** — byte-identical (250 lines, 0% delta).

The `<step_7_diff>` contained exactly one item: the `record_return` late-branch routing fix, with no test deletions / no test_helpers fixes / no test_suite fixes. Per Step 7's own diagnosis (STEP 1: "PRD covers and uniquely determines the outcome … Uniquely derivable; test kept"), this is a **pure implementation bug**, not a PRD silence or PRD/impl mismatch. The existing §3.7 prose (late branch; "a return executed while the reservation is already `OVERDUE` likewise … carries the reservation through to `SETTLED`"; "a return is only valid while the reservation is `PICKED_UP` or `OVERDUE`") and §3.8 ("a settlement reached on the late branch may leave the reservation in `OVERDUE`"; "Finalization is permitted only when a Settlement exists … and the reservation is in `RETURNED` or `OVERDUE`") already pin the corrected behavior. Inserting any clarifying sentence would risk narrowing already-correct prose (NO-NEW-MISMATCH), so prose kept verbatim.

## Step 9: Complete PRD — 2026-06-11T03:40:26.000Z

`PRD_COMPLETED.md` produced from `PRD_FINALIZED.md` via full PRD-vs-implementation scan. 250 → 250 lines (all in-paragraph; 0 new lines/paragraphs/sections), char delta **+3349**.

**Counts:** 7 ambiguity-pins, 6 mismatch-revisions (13 edits total).

**Per-change log:**
- §2.1 RBAC — revise — mismatch — Customer ownership scope extended to own customer record, settlements, fit-checks, ledger entries (cross-customer forbidden) — routes/customers.py:42, settlements.py:23, fit_checks.py:45, ledger_entries.py:18
- §2.10 OCC — revise — mismatch — confirm & retire check version only when supplied (optional); lock & waive require it — reservations.py:105/reservation_ops.py:104, garment_units.py:102, party_orders.py:85, settlements.py:82
- §3.1 clear-cleaning — insert — ambiguity — not-IN_CLEANING / buffer-not-elapsed → ERR_INVALID_STATE; no concurrency field — garment_units.py:73,77
- §3.1 retire — revise — mismatch — expected_garment_unit_version optional (checked only when supplied) — garment_units.py:101-103
- §3.2 customer computed figures — revise — mismatch — deposit_held_cents/balance_owed_cents ledger-derived per §2.9 (hold persists through RETURNED until finalize); open_strike_count counts all DAMAGED settlements — services/views.py:61-70,81-83, ledger.py:33-50
- §3.3 window coherence — insert — ambiguity — pickup window end compares pickup_window_start_iso; event_date == clock rejected; check order — reservations.py:55-60
- §3.4 confirm gates — revise — mismatch — gate order window-conflict → party gates → unit-availability — reservation_ops.py:84-109
- §3.5 fit-check create — insert — ambiguity — no reservation-state precondition (need not be CONFIRMED) — fit_checks.py:14-37
- §3.5 alteration create — insert — ambiguity — no reservation-state precondition — alterations.py:18-39
- §3.7 return — insert — ambiguity — success data is new Settlement object; late-from-PICKED_UP → OVERDUE — reservations.py:148, reservation_ops.py:308-313
- §3.8 finalize — insert — ambiguity — success data is Settlement (no OCC; version unchanged); DEPOSIT_RELEASE posted only when refund > 0 — settlements.py:46-69
- §3.8 waive-fee — insert — ambiguity — net_charge_cents reduction floored at 0 — settlements.py:94
- §3.9 lock & dissolve — revise — mismatch — order posture (ERR_INVALID_STATE) → coordinator (ERR_NOT_COORDINATOR) → version; dissolve moves CONFIRMED members to CANCELLED, bumps party version, no cascade to REQUESTED alterations — party_orders.py:78-86,99-124

Behaviors PRD already pinned uniquely (envelope, pagination, rounding order, late_days ceiling, damage cascade, sweep order, deposit waterfall, fit ordinals, size chart) left unchanged.

---

## Pipeline complete — 2026-06-11T03:40:26.000Z

All 9 steps done. Final state: **65/65 tests pass across all 8 parallel stability rounds**. Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/, test_suite/ (13 files), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ + results.{1..8}.json}.
