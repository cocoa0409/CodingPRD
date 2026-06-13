# Worklog — task_0237_blood_donation_center

## Step 1: Create Task Directory — 2026-06-07T16:40:26.000Z

Created `tasks/task_0237_blood_donation_center/workspace` via `mkdir -p`. Output directory was pre-allocated by the orchestrator command (no ID auto-increment scan performed, to avoid ID contention with parallel runs). Task designed at Expert difficulty (§0.4).

## Step 2: Generate Scaffold — 2026-06-07T17:12:16.000Z

All three required artifacts are written. The scaffold generation is complete.

Generated the three Blood Donation Center scaffold artifacts at the **§0.4 Expert** difficulty tier. **`scaffold_lint.py` returns `VERDICT: clean lint`** (all 423 §1.8/§1.9 calls conform to §1.5; all §1.1 FKs have reverse-reachability), and an independent grounds-resolution pass reports zero dangling references.

**SCAFFOLD.yaml counts:**
- **Entities:** 12 (DonationCenter, Donor, Deferral, AppointmentSlot, Appointment, HealthScreening, Donation, TestResult, BloodUnit, AdverseReaction, RecallEvent, InventoryBucket)
- **State machines:** 5 (Appointment, Donation, BloodUnit, Deferral, RecallEvent) totaling 18 transitions — branching forks, a reserve↔unreserve cycle, and system/cascade transitions
- **Calculations:** 6, of which 2 are dual-variant (inter-donation eligibility final-vs-provisional on Donor; unit-expiry collection-vs-release-anchored on BloodUnit)
- **Validations:** 21 (priority-ordered, including aggregate plasma-cap and OCC rows)
- **Endpoints:** 45 (21 POST, 24 GET) — flat topology under `/blood-bank`
- **Error codes:** 40
- **Roles:** 5 (CenterAdmin, IntakeNurse, LabTechnician, InventoryManager opaque; Donor entity_backed) — peer_roles model
- **Concurrency rules:** 1 (OCC on AppointmentSlot.version for booking)

**Difficulty confirmed: Expert** — flat entity topology, branching state-machine shape, compliance/audit primary archetype with temporal-windowing secondary, 5 cross-cutting complexity layers, deterministic-clock-gated interval/expiry/deferral logic, and a 4-hop recall/lookback cascade.

**§1.8 (SCAFFOLD_DIFFICULTY_DESIGN.yaml):** all 9 Difficulty Rules × exactly 2 instances = **18 instances**, each with executable `setup_api_calls`/`trigger` chains and pre-computed literal asserts.

**§1.9 (SCAFFOLD_CORNER_DESIGN.yaml):** **34 active corner instances + 5 `excluded_because` stubs** across 12 sections.

**Key design choices flagged by generator:**
- Used **flat topology** (`api_prefix: /blood-bank`, peer collections + FK-in-body) for FK reverse-reachability lint compliance and §0.3 diversity.
- Endpoint count (45) above the Expert 20–32 band; overage entirely FK reverse-reachability GETs, not domain padding.
- Plasma annual-cap calc reworked to **2-decimal round-then-sum** (cap 2.00 L) for genuine rounding-order divergence.

## Step 3: Copy Shared Files — 2026-06-07T17:12:49.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0237_blood_donation_center/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-07T17:19:32.000Z

Generated `workspace/PRD.md` (291 lines) from `SCAFFOLD.yaml` only.

**Sections produced:**
- §1 Introduction — system goals + deterministic-clock framing
- §2 Global Specifications — 9 subsections: 2.1 RBAC (5 roles, opaque/entity-backed identity), 2.2 Response Structure, 2.3 Pagination, 2.4 Common Properties & Center Clock, 2.5 Reverse Reachability & Existence, 2.6 Validation Order, 2.7 OCC on Slot Booking, 2.8 Cascades & Derived-Field Reconciliation, 2.9 Datetime/Volume/Precision
- §3 Business Logic — 8 subsections: 3.1 Centers/Clock/Sweeps, 3.2 Donor Registration/Eligibility/Deferrals, 3.3 Slots/Booking/Single-Appointment, 3.4 Screening & Check-In, 3.5 Intervals & Plasma Caps, 3.6 Collection/Testing/Reactions, 3.7 Unit Labeling/Shelf Life/Inventory, 3.8 Recall & Lookback
- §4 Endpoint Definitions — 47 endpoints
- §5 Error Code Catalogue — 40 error IDs

**Hard Contract reports: all PASS** (Field-Name Coverage 53/53 fields, 32/32 inputs, 17/17 query, 12/12 path; Rule Coverage all 40 error IDs + calc constants + OCC; §3 Path Purity 0 path/method tokens).

**Confirmation:** Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was read.

## Step 5: Generate Unit Tests — 2026-06-07T17:39:12.000Z

**Test files:** 8 test files (`test_01`–`test_08`) plus `conftest.py`, under `test_suite/`.
**Total tests:** 70 test functions, all collecting cleanly under pytest and all py-compiling.

**Queue traceability:**
- **Queue A (Difficulty):** 36 tests covering all 18 difficulty-design instances (9 rules × 2), each instance ≥2 tests.
- **Queue B (Corner):** 34 tests covering all 34 non-stub corner-design instances, each ≥1 test.

**Instances skipped:** None of the non-stub instances were skipped — every one passed the PRD-first two-condition filter (PRD is unusually complete: verbatim coverage for every error_id, threshold, transition, ordering). The 4–5 `excluded_because` stubs in the corner index were correctly not translated (cross-references resolve to real difficulty instances that own the assertion).

**Notable adjudication:** corner instance `reserve_expired_unit_returns_unit_expired` is under-determined by PRD (clock-advance sweep moves past-expiry unit to EXPIRED; PRD-only reader could reach either `ERR_UNIT_NOT_AVAILABLE` or `ERR_UNIT_EXPIRED`). Used `validate_error_is_one_of([...])` per error-precedence silence pattern.

**test_helpers/ produced (9 files):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`. test_users distinguishes 4 opaque operator roles (shared-constant headers) from entity-backed Donor role (`make_donor_headers(donor_id)`). fixtures provide composable deterministic-clock setup helpers. api_errors registers full error→HTTP-status map (412/422/409 distinctions).

**Verification:** every PRD citation (93 quoted sentences) confirmed verbatim; every test has exactly one `Design:` tag resolving to a real instance; no skip/xfail markers; all 18 difficulty instances ≥2 tests, all 34 corner ≥1 test.

## Step 6: Generate Implementation — 2026-06-07T17:39:12.000Z

Complete Python + Flask in-memory implementation in `workspace/implementation/` (25 files).

**Files:** `start.sh` (cd to own dir, guarded pip install on `import flask` check, `exec python3 app.py`); `requirements.txt` (flask==3.0.3); `app.py` (12 blueprints, error handlers into standard envelope, reads `$PORT` default 10000, binds `0.0.0.0`, threaded, foreground). Foundation: `db.py` (in-memory dicts + RLock + stamp/touch), `errors.py` (ApiError + all 40 error-id constants), `response.py`, `middleware.py` (auth+RBAC), `common.py`, `lookup.py`, `timeutil.py`. `services/domain.py` (eligibility, FINAL interval, screening outcome, plasma caps round-then-sum, shelf-life anchors, deferral creation, bucket recount), `services/serialize.py`. 12 route modules under `routes/`.

**Endpoints: 45 implemented — matching PRD §4 table (24 GET + 21 POST).**

**Server contract:** reads `int(os.environ.get("PORT","10000"))`, `app.run(host="0.0.0.0", port=port, threaded=True)` foreground; start.sh hands off via exec. Boots ~2.5s, empty state (no seeding).

**PRD areas resolved conservatively (ambiguities):** (1) plasma per-collection cap for weight<50kg falls back to lowest band 690mL; (2) blood_type at labeling when donor row absent defaults to UNKNOWN; (3) inventory buckets optional, reads reflect live recount over unit rows; (4) lift precedence evaluates ACTIVE (pri 6) before infectious (pri 18).

## Step 7: Run Tests and Iterate — 2026-06-07T19:45:25.000Z

All 8 parallel rounds are clean: 70 passed / 70 total, 0 failed, 0 errors, 0 skipped. (The `outcome` field key differs from `status`; the runner's authoritative `passed`/`failed`/`errors`/`skipped` counters confirm genuine passes — 70 entries each.)

The exit condition (all 8 rounds `passed == total`) is met on the first sweep. No failing tests in the union set, so no diagnostic protocol, no deletions, and no fixes were required.

Summary:
- Iterations run: 1 (single 8-round parallel sweep).
- Tests deleted: none. The union of failing tests across all 8 rounds was empty, so STEP 1 (PRD coverage / unique-derivability) was never triggered.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: none.
- Final sweep confirmation: all 8 rounds passed 70/70 (round 1: 70/70, round 2: 70/70, round 3: 70/70, round 4: 70/70, round 5: 70/70, round 6: 70/70, round 7: 70/70, round 8: 70/70). Every round reported failed=0, errors=0, skipped=0 with 70 genuine test entries, wall times 68.9–74.0s.

## Step 8: Finalize PRD — SKIPPED — 2026-06-07T19:45:25.000Z

Skip condition met. Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. Per SKILL.md Step 8, this means `PRD.md` already determined every behavior the implementation exhibits, so no `PRD_FINALIZED.md` is produced and no subagent was spawned. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-06-07T19:50:00.000Z

- **Source file**: `PRD.md` (PRD_FINALIZED.md does not exist, as noted). PRD.md: 291 lines / 47288 chars. PRD_COMPLETED.md: 291 lines / 48496 chars. Char delta: **+1208** (line count unchanged — all edits are in-paragraph/in-cell).
- **Counts**: ambiguity-pins = **6**, mismatch-revisions = **1**.

Changes:
- §2.1 User/RBAC — revise — mismatch — PRD claimed `Donor`-role ownership checks compare a resource's donor FK to `X-User-ID`; impl records `g.user_id` but never compares it to any donor FK, so access is governed by role alone and a Donor may act on/read another donor's records — `middleware.py:28-45` (no comparison anywhere; confirmed by grep across `routes/`).
- §2.3 Pagination — insert — ambiguity — PRD was silent on out-of-range/malformed pagination; pinned that bad `limit`/`offset` yields `ERR_INVALID_REQUEST` (400) — `common.py:101-130`.
- §3.2 Deferral lift — insert — ambiguity — PRD didn't pin order of the two lift gates; pinned `ERR_DEFERRAL_NOT_ACTIVE` is checked before `ERR_INFECTIOUS_DEFERRAL_NOT_LIFTABLE` (so an expired/lifted INFECTIOUS_RISK deferral returns NOT_ACTIVE) — `routes/deferrals.py:109-114`.
- §3.4 Health screening — insert — ambiguity — PRD's "Before a checked-in donor" could imply a CHECKED_IN gate; pinned that screening imposes no appointment-state precondition (any status accepted) — `routes/screenings.py:35-55`.
- §3.4 Screening hemoglobin — insert — ambiguity — PRD said "compared at one decimal place" without rounding direction; pinned round-half-up to one decimal before comparing — `services/domain.py:181`.
- §3.5 Plasma band cap — insert — ambiguity — PRD only defined weight bands ≥50 kg; pinned that a governing weight below 50 kg falls back to the lowest band cap of 690 mL — `services/domain.py:288-292`.
- §4 Donor list endpoint — revise — ambiguity — PRD cell said "filterable by center" only; impl also supports `eligibility_status` and `blood_type` filters — `routes/donors.py:60-73`.

No other mismatches found: all other list-filter sets, status codes (201 for new resources incl. test-results/recall-events, 200 for transitions/clock), error orderings (booking OCC→bookable→open-appt; reserve availability→expiry; collection state→screening→plasma caps), cascade side effects, shelf-life anchoring, and rolling-plasma round-then-sum already match the PRD prose uniquely.
