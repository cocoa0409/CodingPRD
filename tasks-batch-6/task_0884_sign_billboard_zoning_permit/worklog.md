# Worklog — task_0884_sign_billboard_zoning_permit

## Step 1: Create task directory — 2026-07-28T00:00:00.000Z

Created pre-assigned directory `tasks/task_0884_sign_billboard_zoning_permit/` with `workspace/` subfolder (Step 1 index scan skipped — folder pre-assigned to avoid ID contention).

## Step 2: Generate scaffold — 2026-07-28T17:12:00.000Z

The scaffold is complete and passes `scaffold_lint.py` with `VERDICT: clean lint`. All three files safe_load OK.

**Structural profile** (compliance/audit + workflow orchestration; flat topology; parallel/cyclic state machines; segregation-of-duties role model; immediate consistency):
- **12 entities**: Parcel, Applicant, Inspector, SignApplication, Variance, Permit, Inspection, NonConformingRegistration, Violation, RemovalOrder, Billboard, BillboardLease.
- **9 state machines** (SignApplication carries 3: status + two parallel review axes `dimensional_review` × `overlay_review`; Variance is cyclic via REVISION_REQUESTED↔UNDER_REVIEW; Permit/Inspection/Violation/Billboard/BillboardLease with system-swept time transitions).
- **7 calculations**: provisional vs final permit fee (dual-variant, tiered mode-a), billboard registration fee (round-per-face-then-sum, mode-b), non-conforming straight-line vs declining-balance valuation (dual-variant decay), parcel-slot ledger, permit-revenue ledger, illumination-rank threshold.
- **44 endpoints**, **27 error codes**, **13 validation priority layers**, **4 roles** (Applicant/Inspector entity-backed; Planner/ZoningBoard opaque), **2 OCC concurrency rules** (permit-issue on application.version; lease-create on billboard.version).
- A `/_clock/set_current_utc` endpoint (default `2026-05-01T00:00:00Z`) doubles as an ops-run sweep for all time-based transitions.

**Difficulty design (§1.8)**: 9 rules × 2 = **18 instances**. **Corner design (§1.9)**: 8 sections, **39 instances** (33 real + 6 stubs).

**Key fix during generation**: FK reverse-reachability required `api_prefix: /` + single-resource `GET /{id}` on every child entity — 7 GETs added, endpoint count 44.

## Step 3: Copy shared files — 2026-07-28T17:12:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-28T17:20:00.000Z

Generated `workspace/PRD.md`. 5 top-level sections; §2 has 8 subsections, §3 has 8 workflow subsections. **44 endpoints** (matches scaffold), **27 error codes**. Contracts 1/2/3 all PASS.

**Scaffold issues flagged by PRD-gen:**
1. Seven undeclared time constants (PERMIT_TERM_DAYS, RENEWAL_WINDOW_DAYS, RENEWAL_GRACE_DAYS, CURE_PERIOD_DAYS, REMOVAL_COMPLIANCE_DAYS, REGISTRATION_TERM_DAYS, INSPECTION_BUFFER_MINUTES) — no value in any constants block. PRD embedded conventional values: permit term 365, renewal window 30 before / 30 grace after, registration term 365, cure 30, removal-compliance 15, inspection buffer 60 min.
2. Metadata error_code_count says 24 but §1.6 lists 27 (catalog authoritative; all 27 rendered).

## Reconciliation (orchestrator, pre-Step-5/6) — 2026-07-28T17:22:00.000Z

Cross-checked the 7 undeclared constants against the withheld §1.8/§1.9 design worked examples to ensure PRD values agree with test asserts:
- **CURE_PERIOD_DAYS=30** — PINNED (CORNER `cure_violation_before_deadline_succeeds`: "clock at default 2026-05-01, deadline 2026-05-31") ✓ matches PRD.
- **REGISTRATION_TERM_DAYS=365** — PINNED (DIFFICULTY `registration_lapse...`: registered 2026-05-01 → registration_expires_at=2027-05-01) ✓ matches PRD.
- **INSPECTION_BUFFER_MINUTES=60** — PINNED (DIFFICULTY: "30 minutes after the first (< INSPECTION_BUFFER_MINUTES=60) rejected") ✓ matches PRD.
- **PERMIT_TERM_DAYS=365, RENEWAL_WINDOW_DAYS=30, RENEWAL_GRACE_DAYS=30, REMOVAL_COMPLIANCE_DAYS=15** — not exact-tested (corner tests use relative "far outside window" framing); PRD's conventional values are internally consistent.

Added a `global_constants:` block to SCAFFOLD.yaml (after complexity_profile) declaring all 7 values so impl-gen (SCAFFOLD+PRD reader) sees consistent numbers. SCAFFOLD safe_loads OK. PRD needed no patch — its embedded values already match every design-pinned example.

## Step 6: Generate implementation — 2026-07-29T02:36:00.000Z

Built Python+Flask impl at `workspace/implementation/` (app.py ~1050 lines, start.sh, requirements.txt). **44 routes registered** (verified via url_map AND 44 @app.route decorators == scaffold endpoint_count=44; partial-write guard PASS). In-memory only, no seeding; logical clock defaults 2026-05-01T00:00:00Z; ISO-8601 3-frac-digit +Z timestamps. Envelope meta/response_type/data verbatim; error body {error_id,message}; pagination limit/offset/total_count/has_more in meta. Parcel slot counters recomputed from live ACTIVE permits (invariant active_permit_count+available_sign_slots==max_signs auto-holds). Validation precedence per PRD §2.8. Variance dimensional relief substitutes granted figure for AREA/HEIGHT/SETBACK; any grant bumps application.version (OCC drift source). Decimal ROUND_HALF_UP money; per-face rounding before sum for registration fees. Smoke suites pass: full sign-permit lifecycle, OCC 412, fees (permit 18600, digital billboard reg 15000), slot ledger, lease overlap/abut, variance SoD 403, overlay+illumination gating, non-conforming amortization, violation cure/escalate/removal cascade, clock sweep. NOTE: cure-after-deadline returns ERR_INVALID_STATE (no dedicated catalog error).

## Step 5: Generate unit tests — 2026-07-29T02:47:00.000Z

Generated test_helpers/ (9 files) + test_suite/ (6 files, **69 tests**) under design-index-only contract. Difficulty §1.8: all 18 instances ≥2 tests each (36 tests). Corner §1.9: 32/33 non-stub covered. Every docstring one Design: tag + verbatim PRD quotes (programmatically confirmed literal substrings). Pre-computed values re-derived: provisional 61100/final 43600, straddle 101100, per-face reg 15000, straight-line 600000/declining 640000. Suite collects 69 tests, 0 import errors.
**SKIPPED 1 instance (logged gap):** Corner/entities/application_bad_parcel_fk_returns_parcel_not_found — unique-derivability fail: POST /applications bad body parcel_id ambiguous under PRD §2.8 (pt3 generic ERR_NOT_FOUND vs pt4 typed-root ERR_PARCEL_NOT_FOUND only for path-keyed roots). Two faithful readers could return either.

## Step 7: Stability sweep + iterate — 2026-07-29T03:00:00.000Z

**CLEAN PASS — 69/69 across all 8 parallel rounds, ZERO fixes.** Ran sweep.sh (2 waves of 4). Iterations: 1. Tests deleted: none. test_helpers/ fixes: none. implementation/ fixes: none. Per-round: all 8 rounds 69/69, zero flakiness. results.{1..8}.json durable on disk. Diagnostic protocol never triggered (empty union failure set).

## Step 8: Finalize PRD — 2026-07-29T03:00:30.000Z — SKIPPED

Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits. Per skip condition, Step 8 not spawned; no PRD_FINALIZED.md produced.

## Step 9: PRD completeness scan — 2026-07-29T03:04:00.000Z

Produced `workspace/PRD_COMPLETED.md` (started from PRD.md; no PRD_FINALIZED.md since Step 8 skipped). Source PRD.md 288 lines/39,646 chars → PRD_COMPLETED.md 288 lines/40,663 chars (+1,017 chars, no new lines/sections, all in-paragraph). **6 ambiguity-pins + 1 mismatch-revision:**
- §2.3 Pagination — insert/ambiguity — records sharing created_at tie-broken by creation sequence (earliest first) under shared logical clock (app.py:273).
- §3.2 Dimensional axis (setback) — revise/mismatch — impl lowers setback floor to granted SETBACK-variance value; reworded to "effective setback floor" mirroring area/height (app.py:745-748).
- §3.2 review — insert/ambiguity — either review axis recordable only while SUBMITTED else ERR_INVALID_STATE (app.py:730-731).
- §3.2 decide — insert/ambiguity — decision legal only from SUBMITTED; approval without both review conditions → ERR_INVALID_STATE (app.py:773-778).
- §3.3 variance GRANT — insert/ambiguity — granted_value defaults to requested_value when board omits it (app.py:873).
- §3.4 permit renew — insert/ambiguity — renewing permit with fee_paid=false → ERR_INVALID_STATE (app.py:979-980).
- §3.7 violation cure — revise/ambiguity — cure after cure_deadline → ERR_INVALID_STATE (no dedicated cure-window code) (app.py:1188-1189).
Already-pinned (no change): escalate-before-deadline ERR_CURE_PERIOD_ACTIVE; body-FK ownership before existence; live parcel slot recomputation + invariant; variance grant bumps application.version; per-face ROUND_HALF_UP reg fee + round-before-sum; ISO-8601 3-frac +Z + 2026-05-01 default clock.

---
## PIPELINE COMPLETE — task_0884_sign_billboard_zoning_permit (RESUMED from Step 5)

Expert difficulty. **69/69 tests pass across all 8 parallel stability rounds — CLEAN PASS, 0 impl fixes, 0 test deletions.** 12 entities / 44 endpoints / 27 errors / 9 state machines / 7 calculations / 4 roles / 2 OCC rules. Step 8 skipped (0 Step-7 fixes). Step 9 = 6 ambiguity-pins + 1 mismatch-revision. Resumed cleanly from Step 4→5 session-limit kill; no artifact regeneration.
