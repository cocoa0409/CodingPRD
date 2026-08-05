# Worklog — task_0870_water_sewer_tap_capacity_fee

## Step 1: Create task directory — 2026-07-27

Created `tasks/task_0870_water_sewer_tap_capacity_fee/` and `workspace/` (pre-assigned folder; index scan skipped).

## Step 2: Generate scaffold (Expert) — 2026-07-27

All checks pass: clean lint, all grounds resolve, no forbidden concurrency vocabulary, 9 rules × 2 instances = 18 difficulty instances well-differentiated.

Generated three lint-clean scaffold artifacts at Expert difficulty, authored purely from the scenario + skill spec (no sibling tasks consulted). All three files pass `scaffold_lint.py` with `VERDICT: clean lint`.

**Structural counts**
- Entities: **14** (ConnectionApplication, MeterSizeSchedule, FeeSchedule, Inspector, MeterCrew, AvailabilityDetermination, MainExtensionProject, DeveloperAgreement, EscrowTransaction, Inspection, BackflowAssembly, MeterSet, ServiceAccount, LatecomerReimbursement)
- Endpoints: **65** (flat topology, `api_prefix: /`; many filtered-list/single GETs for FK reverse-reachability)
- State machines: **9**; Calculations: **9**; Validations: 21 (priority-ordered); Errors: 19; Roles: 5; OCC rules: 2

**Notable design decisions**
- Primary archetype pricing_engine + workflow_orchestration; flat topology; `role_model: segregation_of_duties`.
- Dual-variant calcs on different domains: capacity_fee NEW vs REDEVELOPMENT and latecomer share FRONT_FOOTAGE vs AREA.
- Combinatorial: capacity_fee = tiered multi-input (eru × service branch × use multiplier); total_fees_due = circular-looking (discount keyed on gross, gross depends on admin fee — evaluation order pinned).
- Cyclic state machines: ConnectionApplication revision loop and Inspection reinspection loop.
- Transitive cascades: depth-3 (project ACCEPTED → agreement COMPLETION_PENDING → availability flipped) and depth-2 (meter-set inspection PASS → MeterSet INSTALLED → application READY).
- SoD (four-eyes): availability reviewer cannot approve same application (`ERR_SEGREGATION_OF_DUTIES`, `availability_reviewer_id`).
- OCC on two parents: escrow DRAWDOWN vs `DeveloperAgreement.version`, latecomer create vs `MainExtensionProject.version` (412).
- Two temporal-overlap semantics: Inspector half-open `[start,end)` vs MeterCrew closed-interval + 60-min buffer.
- Two conserved-quantity invariants: escrow money and reimbursement pool.
- Constants all pinned inline (`MAX_CONNECTION_DISTANCE_FT: 200`, `APPOINTMENT_BUFFER_MINUTES: 60`, admin pct/cap, volume discount). No logical clock endpoint; ordering tie-breaks use `created_at`.

## Step 3: Copy INSTRUCTION.md — 2026-07-27

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-27

PRD generated at `workspace/PRD.md` (296 lines). Domain: water-sewer-tap-capacity-fee — municipal pricing engine + workflow orchestrator.

Sections: §1 Introduction; §2 Global Specs (10 subsections incl. RBAC per-role identity translation, Response Structure, Pagination, Common Properties/Versioning, Monetary Precision/Rounding, OCC, Cascading Reconciliation, Path/Reference Validation, SoD, Validation Ordering); §3 Business Logic (8 lifecycle subsections); §4 65-endpoint table; §5 19-error catalogue.

Coverage: Contract 1 (Field-Name) PASS — 71 field/param names verbatim (`status` added to §2.4). Contract 2 (Rule) PASS — 21 validations w/ priority ordering, both OCC rules, 9 state machines, 3 cascade chains, 8 calculations (capacity_fee dual-variant, total_fees_due ordered admin-then-discount, latecomer dual-variant, escrow+reimbursement conservation, 200-ft inclusive boundary, half-open inspector overlap, closed-interval+60-min crew buffer). Contract 3 (§3 Path Purity) PASS. Withheld design files not read.

## Step 5: Generate unit tests — 2026-07-27

test_helpers/ (9 files) + test_suite/ (8 files + conftest); **65 tests total**, all green on collection/compile.
Coverage (design-index-only): Queue A (Difficulty) **18/18** instances translated (2 tests each). Queue B (Corner) **29/29 non-stub** translated (≥1 each); 2 `excluded_because` stubs correctly not translated. 0 skips beyond stubs — clean fully-derivable Expert PRD. Every docstring ends with verbatim `Design:` tag; PRD citations spot-checked; no scaffold leakage. Pre-computed expected values independently recomputed.

## Step 6: Generate implementation — 2026-07-27

`workspace/implementation/` — `app.py` (~1400 lines single-module Flask), `requirements.txt` (Flask 3.0.3), `start.sh` (guarded-install foreground, reads $PORT default 10000, binds 0.0.0.0). **65 endpoints** implemented. Smoke-tested happy path, capacity fee dual-variant, SoD, 3 cascade chains, escrow conservation, OCC 412 both paths, temporal overlap semantics, latecomer dual-variant, RBAC.
Key decisions: in-memory dicts wiped each boot, no seeding; single ISO-8601 serializer (`Z`, 3 frac digits), input datetimes echoed; dashed UUIDs; `Connection: close` on every response. Version bookkeeping: availability-file stamps reviewer without app-version bump; latecomer collection updates pool without project-version bump (only assessment creation bumps); escrow close/terminate single bump. Validation ordering per PRD §2.10. Ownership → `ERR_UNAUTHORIZED` 403. complete-install w/ FAILED backflow → `ERR_INVALID_STATE` 409.

## Step 7: Test and iterate — 2026-07-27

All 8 rounds pass **65/65**. Clean sweep.
Iterations run: 2 (initial diagnostic sweep + 1 fix + confirming sweep).
Tests deleted: None.
Fixes to test_suite/ (STEP 2 fixture bug): `test_01_application_lifecycle.py::test_approve_from_draft_invalid_state` — added `ensure_meter_schedule()` before creating the app. App defaults `meter_size="ONE"` but test never created a meter-size schedule row. PRD §2/§3.4: approval's `meter_size` schedule-existence check precedes the state check → PRD-faithful impl correctly returned `ERR_METER_SIZE_UNKNOWN` before `ERR_INVALID_STATE`. Seeding the schedule surfaces the intended `ERR_INVALID_STATE`.
Fixes to implementation/: None — impl error precedence correct per PRD.
Zero flakiness; single consistent failure was the fixture issue (not a race), resolved deterministically.

## Step 8: Finalize PRD — 2026-07-27

PRD_FINALIZED.md produced (296 lines, byte-identical to PRD.md, 0% delta). No edits: the sole Step 7 fix was a test-fixture correction (missing `ensure_meter_schedule()` seed); impl error precedence (`ERR_METER_SIZE_UNKNOWN` before `ERR_INVALID_STATE`) already matched PRD §2.10/§3.4 verbatim. No PRD silence/mismatch → verbatim copy is the correct outcome.

## Step 9: Complete PRD — 2026-07-27

PRD_COMPLETED.md written (296 lines, +1139 chars). Ambiguity-pins + mismatch-revisions (7–8 edits, all in-paragraph):
- §3.3 availability — `availability_reviewer_id` stamp does NOT refresh `updated_at`/`version` (ambiguity).
- §3.3 escrow postings — revise: order state → drawdown-sufficiency (`ERR_ESCROW_INSUFFICIENT`) → `ERR_STALE_VERSION` → body validation; state gate applies to all posts incl REFUND (mismatch).
- §3.4 capacity fee — `use_type` absent from `use_multipliers` defaults to 1.0 (ambiguity).
- §3.4 fee assessment — no active rate card at approval → `ERR_VALIDATION` 400 (ambiguity).
- §3.5 meter-set complete-install — FAILED backflow → `ERR_INVALID_STATE` 409 (ambiguity).
- §3.6 backflow install — `serial_number` must be non-empty → `ERR_VALIDATION` (ambiguity).
- §3.7 pay-fees — owning applicant may pay regardless of state; `amount_cents` non-negative int, no state guard (ambiguity).
- §3.8 collect latecomer — pool update on collect does NOT bump project `version`/`updated_at` (mismatch).
Left unpinned: list-endpoint query filters (additive read conveniences), opaque `account_number` format.

## Pipeline complete — 2026-07-27

All 9 steps done. Final state: 65/65 tests pass across 8 stability rounds. Artifacts: SCAFFOLD*.yaml (3), workspace/{PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, INSTRUCTION.md, implementation/}, test_helpers/, test_suite/.
