# Worklog — task_0391_k12_field_trip_permission

## Step 1: Create Task Directory — 2026-06-17T00:00:00.000Z

Created `tasks/task_0391_k12_field_trip_permission/` with `workspace/` subdirectory. Index pre-assigned (0391) to avoid contention with concurrent pipeline runs. Difficulty: Expert (applies to Step 2 scaffold generation only).

## Step 2: Generate Scaffold (Expert) — 2026-06-17T00:00:00.000Z

All three scaffold artifacts are generated and pass the linter cleanly. I did not look at any sibling task directory — the design was derived purely from the scenario description and the scaffold-generator skill spec.

**Lint verdict:** `clean lint` — 54 endpoints, 13 entities, 18 §1.8 instances, 35 active §1.9 instances, 543 calls all conforming; every FK reverse-reachable.

**Complexity profile (Expert):** primary archetype multi-party negotiation (Teacher→Principal→DistrictAdmin approval chain) blended with quota/allocation; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; **flat** topology (root prefix `""`, every entity a top-level collection with FK-filtered list GETs — required to satisfy the linter's FK reverse-reachability check, which cannot resolve deeply-nested collections).

**Scaffold contents:**
- **13 entities:** Student, Guardian, Vehicle, ScholarshipPool, FieldTrip (aggregate root, OCC `version`), TripApproval, PermissionSlip, EmergencyContact, ScholarshipGrant, Chaperone, TransportBooking, FeeTransaction, AttendanceRecord.
- **4 state machines:** FieldTrip (cyclic — reject loops back to DRAFT, branching approvals, cancel cascades), PermissionSlip (parallel signature_status × payment_status × participation dimensions, each cyclic), Chaperone (invited→confirmed→cleared with withdraw revert), TransportBooking (requested→confirmed→cancelled).
- **8 calculations:** chaperone_ratio_requirement (tiered+nonlinear), slip_fee_due (dual-variant provisional/final), per_student_cost_allocation (waterfall remainder rounding), voluntary_withdrawal_refund (dual-variant), collected_fees_reconciliation + vehicle_seat_reservation (conserved-quantity invariants), vehicle_window_overlap + chaperone_window_overlap (two overlap geometries).
- **14 validation priorities** (auth → role → existence → ownership → approval-step → state → cross-entity → temporal overlaps → safety ratio → capacity → emergency-contact → scholarship fiscal → payment → empty-roster/headcount → OCC 412).
- **54 endpoints**, **53 error codes** (all triggerable), **1 concurrency rule** (OCC roster-lock supersede), **4 roles** (Teacher/Guardian entity_backed:Guardian; Principal/DistrictAdmin opaque).

**Expert difficulty reflected in §1.8/§1.9:**
- §1.8 has all 9 difficulty rules × exactly 2 instances (18 total), each grounded in declared elements with pre-computed literal asserts.
- §1.9 spans all 8 claim-extraction sections (35 active corner instances + 7 `excluded_because` stubs that cite real §1.8 instances).

## Step 3: Copy Shared Files — 2026-06-17T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-17T00:00:00.000Z

Generated PRD at `workspace/PRD.md` (330 lines, 5 top-level sections + 22 subsections). §4 has all 54 endpoints; §5 has all 53 error codes. Hard contracts (field coverage, rule coverage, path purity) all PASS. Did NOT read either withheld design file (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml).

## Step 5: Generate Unit Tests — 2026-06-17T00:00:00.000Z

Generated complete test infrastructure from the two design indices, with PRD as controlling contract.

### Test helpers — 9 files in `test_helpers/`
`__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

### Test suite — 11 files in `test_suite/`
`conftest.py` + 10 domain-named test files (`test_01_…` through `test_10_…`).

### Counts
- **69 test functions**, every one carrying exactly one verbatim `Design:` tag (no untagged / dual-tagged), 0 `skip`/`xfail`/`skipif`.
- **Queue A (Difficulty):** 17 of 18 instances translated, 2 tests each (34 tests).
- **Queue B (Corner):** all 35 non-stub instances translated, 1 test each (35 tests); the 7 `excluded_because:` stubs correctly not translated.

### Skipped instance (1) — PRD-coverage gap
- `Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_award` — asserts a scholarship grant against an UNSIGNED slip returns `ERR_SLIP_NOT_SIGNED` (state beats fiscal). Skipped: PRD §3.7 lists only the two fiscal bounds for grants and never states a grant requires a SIGNED slip; `ERR_SLIP_NOT_SIGNED` is named in PRD only for revoke (§3.3) and pay (§3.7). A PRD-only implementer would not uniquely derive this outcome. Sibling instance under same rule is fully covered.

### Validation
All test_helpers + 10 modules import cleanly; all 69 tests `pytest --collect-only` successfully. C1 verbatim-citation audit and Design-tag resolution verified.

## Step 6: Generate Implementation — 2026-06-17T00:00:00.000Z

Generated complete Python + Flask implementation at `workspace/implementation/`.

### Files created (12)
`start.sh`, `requirements.txt`, `app.py`, `db.py`, `response.py`, `errors.py`, `middleware.py`, `validation.py`, `lookups.py`, `calc.py`, `serialize.py`, `routes.py`.

### Endpoint count
54 method+path endpoints, matching PRD §4 table 1:1.

### Storage / state
Fully in-memory (Python dicts in `db.Store`, keyed by UUID id). No SQLite, no JSON-on-disk, no /tmp. Append-only records carry only `id`/`created_at`; conserved quantities computed live from ledgers at read time; cross-entity recomputes bump parent `version`/`updated_at`. No seeding — fresh boot reports total_count=0 for all 13 collections.

### start.sh
Reads `$PORT` (default 10000), binds `0.0.0.0`, foreground via `exec`, guarded dependency install, starts empty with zero seeded data.

### Note
When a scholarship award violates both pool-remaining and slip-waivable bounds simultaneously, code returns `ERR_SCHOLARSHIP_POOL_EXHAUSTED` first, matching PRD §3.7 textual order.

## Step 7: Test and Iterate — 2026-06-17T00:00:00.000Z

**Iterations run:** 3 sweep iterations (1 baseline at 66/69 + 2 confirmation sweeps after fixes). Final state: two consecutive clean 8-round parallel sweeps (16 rounds total), every round 69/69 with no failures and no dropped result files.

**Baseline failures (union across all 8 rounds):** 3 tests failing consistently, plus an infrastructure flake that surfaced after the first fix batch.

### Tests deleted
None. No test was found PRD-silent or non-uniquely-derivable.

### Fixes applied to `test_suite/`
- **`test_08_state_transitions.py`** — `test_district_step_on_pending_principal_returns_not_awaiting_district` (renamed to `..._returns_invalid_step`): the test sent `step=DISTRICT` while the trip was `PENDING_PRINCIPAL` and asserted `ERR_TRIP_NOT_AWAITING_DISTRICT`. This is a TEST BUG (STEP 2 — assertion contradicts PRD's pinned error precedence). PRD §2.11 and §3.2 explicitly state the step-match check yields `ERR_INVALID_APPROVAL_STEP` "before the state precondition is examined." Under the PRD, `ERR_TRIP_NOT_AWAITING_DISTRICT` is unreachable for a DISTRICT step. Corrected the expected error to PRD-faithful `ERR_INVALID_APPROVAL_STEP` (error_id → error_id, not a weakening).

### Fixes applied to `implementation/`
- **`routes.py`** — added `_recompute_all_provisional_fees(trip)` and called it from `sign_slip` and `revoke_slip` after `signed_count` changes. Previously only the slip being signed/revoked had its provisional fee recomputed, leaving earlier-signed slips stale (e.g. a slip signed when `signed_count=1` kept `fee=11000` instead of recomputing to `4334` after `signed_count` reached 3). PRD §3.7: provisional transport share is `transport_cost_cents / live signed_count`, "an estimate that shifts as other guardians sign and revoke."
- **`app.py`** — switched server host from Werkzeug dev server to `waitress` (with threaded fallback). Under 8 concurrent rounds × per-test-server reboots, the dev server occasionally dropped connections (`BadStatusLine`) and once failed to emit a results file under peak CPU contention. PRD-neutral hosting change.
- **`requirements.txt`** — added `waitress==3.0.0`.
- **`start.sh`** — extended install guard from `import flask` to `import flask, waitress`.

## Step 7-verify (resumed by parent orchestrator) — 2026-06-17T22:05:00.000Z

The original nested `claude -p` orchestrator ended its print-mode turn while delegating Step 7's re-verification sweep to background processes; those were orphaned on process exit and Steps 8–9 never ran. Parent session re-ran a fresh 8-round parallel per-test-server sweep against the on-disk implementation: **all 8 rounds 69/69, failing-union = 0.** Step 7 state confirmed genuinely green. Resumed pipeline at Step 8.

## Step 8: Finalize PRD — 2026-06-17T22:08:00.000Z

PRD.md = 330 lines, PRD_FINALIZED.md = 330 lines (2 lines revised in place, 0%-delta line count). Two edits, both §3.3:
- §3.3 (sign) — revise — on a successful sign the server recomputes provisional `fee_due_cents` for every currently `SIGNED` slip on the trip, not only the triggering slip — `routes.py:494-497` → `_recompute_all_provisional_fees` (`routes.py:935-951`).
- §3.3 (revoke) — revise — the revoke cascade also recomputes provisional `fee_due_cents` for every still-`SIGNED` slip after `signed_count` decreases (PRD originally omitted fee recomputation on revoke) — `routes.py:514-517`.
Other Step 7 items out of scope: the `test_08` fix was a fixture correction to PRD-faithful `ERR_INVALID_APPROVAL_STEP` (already pinned by §2.11/§3.2); waitress/requirements/start.sh are PRD-neutral hosting changes.

## Step 9: Complete PRD — 2026-06-17T22:14:00.000Z

PRD_FINALIZED.md (source) = 330 lines / 47,734 chars; PRD_COMPLETED.md = 330 lines / 49,299 chars (char-delta +1,565, line-delta 0). 5 changes: 4 ambiguity-pins, 1 mismatch-revision.
- §2.3 Pagination — insert — ambiguity — out-of-range `limit` clamped 1↔100, negative `offset` clamped to 0, non-integer `limit`/`offset` → `ERR_VALIDATION` — `validation.py:104-122`.
- §3.2 Approval chain — insert — ambiguity — `comment` defaults null; approvals endpoint returns 201 (appends a `TripApproval`) — `routes.py:268, 289-299`.
- §3.3 Slips — insert — ambiguity — slip creation has no trip-state precondition; initial `fee_due_cents` is 0 until first fee event — `routes.py:423-448`.
- §3.7 Scholarships — revise — mismatch — award bound is cumulative (sum of ACTIVE awards + new ≤ waivable), gross from slip's current transport share — `routes.py:643-651`, `calc.py:97-109`.
- §3.11 Reading back — insert — ambiguity — single-item reads for TripApproval/EmergencyContact/FeeTransaction/AttendanceRecord return `ERR_VALIDATION` (422) for unresolvable id (no `*_NOT_FOUND` code) — `routes.py:417, 623, 876, 919`.

**Pipeline complete: all 9 steps done. Final state — 69/69 tests passing across all 8 concurrent per-test-server rounds.**
