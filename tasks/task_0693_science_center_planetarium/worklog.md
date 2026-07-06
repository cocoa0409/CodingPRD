# Worklog — task_0693_science_center_planetarium

## Step 1: Create Task Directory — 2026-06-28T15:32:40.000Z

Task directory pre-assigned: `tasks/task_0693_science_center_planetarium` (Step 1 scan/index-calc skipped per orchestration arguments). Ensured `workspace/` subdirectory exists. Difficulty: **Expert** (passed to Step 2 scaffold generator only).

## Step 2: Generate Scaffold (Expert) — 2026-06-28T15:51:14.000Z

Generated all three scaffold artifacts for **task_0693_science_center_planetarium** at **Expert** difficulty, working solely from the scenario description and the scaffold-generator SKILL.md (no sibling tasks consulted). All files written to `tasks/task_0693_science_center_planetarium/`:

- `SCAFFOLD.yaml` (§1.0–§1.7; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts:**
- **Entities: 11** (Venue, Membership, ShowEvent, ShowBooking, GroupBooking, ProgramSession, Registration, RentalEvent, Sponsor, Contribution, AccommodationRequest) — Expert band 10–15 ✓
- **Endpoints: 59** (34 POST + 25 GET, incl. 2 test-driving `/_clock/set_current_utc` + `/_sweeps/run`). Above the 20–32 band, but scenario-driven: the prompt names 8 distinct subdomains and every endpoint is load-bearing (CRUD, state actions, mandatory FK reverse-reachability GETs, or test-recipe usage). Difficulty is in the coupling, not the count.
- **Error codes: 22** — Expert band 18–30 ✓; all triggerable, no orphans
- **Calculation variants: 3+** — 5 calculations, 2 carrying explicit `variants:` (group_invoice_total DEPOSIT/FINAL, rental_quote DEPOSIT/FINAL), plus per-tier branching in show_admission_pricing/program_tuition_pricing/astc_reciprocal_eligibility ✓
- **State machines: 9** (ShowEvent, ShowBooking, ProgramSession, Registration, GroupBooking, RentalEvent, Membership, Sponsor, AccommodationRequest). **Cycle dimensions on 3 distinct entities**: ShowEvent (OPEN↔SOLD_OUT), ProgramSession (ENROLLING↔FULL), Membership (ACTIVE↔EXPIRED renewal). Expert band 4+ with cycles ✓

**Other structural facts:** 3 OCC concurrency rules (ShowEvent/ProgramSession/Sponsor version, all 412), 20 prioritized validations, 8 peer roles. Profile: temporal_windowing + quota_allocation, graph topology, cyclic state shape.

**Design coverage:** §1.8 has exactly 18 instances (2 per each of the 9 Difficulty Rules). §1.9 has 41 active instances + excluded_because stubs cross-referencing §1.8.

**Validation:** `scaffold_lint.py` returns `VERDICT: clean lint` (235 calls scanned, checks a–f all pass). Enum closure verified, no orphan errors, no duplicate priorities.

## Step 3: Copy Shared Files — 2026-06-28T15:51:14.000Z

Copied `INSTRUCTION.md` → `tasks/task_0693_science_center_planetarium/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-28T15:56:30.000Z

**File written:** `workspace/PRD.md` — 309 lines (read SCAFFOLD.yaml only; both design YAMLs withheld).

**Major sections:** §1 Introduction; §2 Global Specifications (10 subsections: RBAC, response envelope, pagination, common props + logical clock, deferred sweeps, OCC, hierarchical cascades, nested retrieval, money/precision, venue capacity/windows/buffers); §3 Business Logic (10 subsections by entity lifecycle + validation-priority subsection); §4 Endpoint Definitions (4-column table); §5 Error Code Catalogue (2-column table).

**Documented coverage:** 11 entities (Contribution has common_fields:false — id+created_at only, called out); 60 endpoints (incl. `/_clock/set_current_utc`, `/_sweeps/run`); 22 errors; 9 state machines (all transitions, precondition+error pairings, depth-3 cascades, cyclic OPEN↔SOLD_OUT / ENROLLING↔FULL / ACTIVE↔EXPIRED); 5 calculations (show_admission_pricing, group_invoice_total DEPOSIT/FINAL, program_tuition_pricing, rental_quote DEPOSIT/FINAL, astc_reciprocal_eligibility) rendered as precise prose; 3 OCC rules (HTTP 412).

**Hard Contract reports:** Contract 1 (Field-Name Coverage) 75/75 present, 0 missing — PASS. Contract 2 (Rule Coverage) all 22 error IDs in §2/§3 narrative, 47/47 state+enum values, 8/8 roles, 20-rule priority order, 3 OCC, all cascades + 5 calculations — PASS. Contract 3 (§3 Path Purity) 454 §3 backtick tokens, 0 paths/methods leaked — PASS. Withheld design files and sibling tasks not read.

## Step 5: Generate Unit Tests — 2026-06-28T16:10:11.000Z

**Test files:** 9 test files + `conftest.py` in `test_suite/`
- `test_01_pricing_and_invoicing.py` (4) — dual-variant deposit/final, combinatorial per-seat formulas
- `test_02_lifecycles_and_cascades.py` (8) — state cycles, depth-3 cascades, cross-entity gating, compensation
- `test_03_validation_priority_and_boundaries.py` (7) — precedence, capacity boundary, buffer-aware overlap
- `test_04_entities_crud.py` (11) — creation/retrieval/listing/defaults/computed/system/immutability/parent-type
- `test_05_state_machines.py` (9) — invalid/terminal/initial/sweep/guard/cascade/bubble-up transitions
- `test_06_calculations.py` (6) — show pricing tiers, early-bird tuition, ASTC eligibility
- `test_07_validations_and_errors.py` (8) — time windows, party-size, accessibility, venue-type, pagination, conflicts, conditional refund
- `test_08_rbac_concurrency_consistency.py` (7) — RBAC, OCC stale-version, expiry sweep, immediate consistency
- `test_09_difficulty_complementary.py` (17) — second depth test per difficulty instance

**Total: 77 tests** (all collect cleanly). Queue A (Difficulty): 36 tests — all 18 difficulty instances ≥2 tests each. Queue B (Corner): 41 tests — all 41 non-stub corner instances ≥1 test each.

**Instances skipped:** 7 — all `excluded_because:` stubs in the corner index (NOT translated, per spec; the cited difficulty instance owns the assertion). No PRD-first filter skips were needed — every non-stub instance had verbatim PRD coverage and unique derivability.

**test_helpers/ files (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`. All 8 roles `identity: opaque` → shared-constant headers only (no entity-backed builders). All tests have exactly one `Design:` tag resolving to a real instance; PRD citations survive whitespace-normalized grep; no skip/xfail; all files byte-compile.

## Step 6: Generate Implementation — 2026-06-28T16:10:11.000Z

**Source files** in `workspace/implementation/`: `start.sh` (foreground `exec python3 app.py`, reads `$PORT` default 10000, binds `0.0.0.0`, guards pip-install on `import flask`); `requirements.txt` (flask==3.0.3); `app.py` (blueprints, ApiError + 404/405/400/generic handlers, threaded); `errors.py` (full §5 catalogue as (id, http) tuples); `response.py` (exact envelope meta/response_type/data); `clock.py` (logical clock + ISO helpers); `db.py` (in-memory store, common fields, touch); `middleware.py` (X-User-ID/X-User-Role auth + RBAC, 8 peer roles); `services/` (common, serialize, lookups, calculations, show_logic, program_logic); `routes/` (one blueprint per resource group — venues, memberships, shows, show_bookings, group_bookings, programs, registrations, rentals, sponsors, accommodations, system — all 60 endpoints).

**Storage:** in-memory only, one dict per entity type keyed by server-minted UUID on a single global `DB` recreated fresh per process. No seeding (fresh boot `GET /venues` → `[]`). RLock guards mutations; `_created_seq` gives deterministic created_at ASC for pagination; internal `_`-prefixed fields stripped by serializer.

**Logical clock & sweeps:** clock defaults `2026-03-01T00:00:00Z`, advanced via `POST /_clock/set_current_utc`; business logic never uses wall-clock (only `api_request_timestamp`). `POST /_sweeps/run` at current logical instant: (1) ACTIVE memberships past expires_at → EXPIRED; (2) HELD show bookings past held_at+30min → CANCELLED, recompute seats_sold, bubble SOLD_OUT→OPEN.

**5 calculations & OCC:** show_admission_pricing (per-seat discount round-half-up before ×party_size; PATRON/FAMILY/INDIVIDUAL tiers); group_invoice_total (DEPOSIT=floor(25%×estimate grand_total); FINAL balance=actuals−deposit; 1 free chaperone/10 students at 70%); program_tuition_pricing (percent step then flat 1000 early-bird if pre-enroll<3, floored 0); rental_quote (marginal tiers 500/300 + base; DEPOSIT floored 25%, FINAL full); astc_reciprocal_eligibility (eligible AND ACTIVE AND home_zip[:3]!="606"). OCC: expected_show/session/sponsor_version vs live parent version → ERR_STALE_* (412). Validation precedence per §3.10. Cascades verified (depth-3 show-cancel, registration-cancel→waitlist). start.sh boots foreground reading $PORT; smoke tests across every workflow pass.

## Step 7: Test & Iterate to Green — 2026-06-28T16:32:03.000Z

### Step 7 fix-subagent summary (verbatim)

**Iterations run:** 2 (1 baseline diagnostic sweep + 1 confirmation sweep after fixes). Baseline was deterministic: 61/77 passing, 16 failing identically in all 8 rounds (no flakiness — every failure reproduced every round).

**Tests deleted:** None. Every failing assertion traced to a verbatim PRD rule and was uniquely derivable; all 16 failures were test-artifact bugs, not implementation bugs.

**Fixes applied to test_suite/ (STEP 2 — test bugs, made the tests MORE faithful to PRD):**

*Category 1 — missing `expected_status=201` on create-success validations (14 failures).* PRD §line 220 states verbatim: "Operations that create a brand-new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or run an administrative action return `200 OK`." The implementation correctly returns 201 for all create endpoints. The failing tests called `validate_success(api.create_*(...))` without `expected_status=201`, and `validate_success` defaults to expecting 200 — so they asserted the wrong status code against a PRD-mandated 201. Added `expected_status=201` to the create-resource `validate_success` calls in: test_01_pricing_and_invoicing.py (3 calls), test_02_lifecycles_and_cascades.py (2), test_03_validation_priority_and_boundaries.py (4), test_07_validations_and_errors.py (1), test_09_difficulty_complementary.py (8). State-transition calls correctly left expecting 200.

*Category 2 — overfulfillment precedence (2 failures).* Both set up a sponsor already FULFILLED, then attempted a further contribution expecting `ERR_OVERFULFILLMENT`, but got `ERR_INVALID_STATE`. Per PRD §line 216 the fixed priority order places `ERR_INVALID_STATE` ahead of `ERR_OVERFULFILLMENT`, and PRD §3.8 defines contribution-recording transitions only from PLEDGED/PARTIALLY_FULFILLED — a FULFILLED sponsor has no defined transition, so the implementation's `ERR_INVALID_STATE` is PRD-faithful. Fixed the test setups to leave the sponsor PARTIALLY_FULFILLED (contribute 3000 of 5000, then 3000 again → overshoot while still accepting).

**Fixes applied to test_helpers/:** None.
**Fixes applied to implementation/:** None — the implementation was PRD-faithful throughout.
**Final sweep confirmation (subagent):** passed == total == 77 in all 8 parallel rounds.

### Orchestrator independent verification (post-subagent)

The Step 7 subagent cleaned up its results files, so the orchestrator independently re-ran the sweep to confirm green and regenerate the artifacts. First attempt at full **8-way concurrency** surfaced flakiness: only 1 of 8 rounds was 77/77; the other 7 each had 1 ERROR ("API server could not be restarted before <test>", 15s boot timeout) and one round had a `ChunkedEncodingError: Connection broken` — **all host-saturation artifacts** (8 concurrent per-test-server sweeps × per-test Flask reboots overwhelm the 8-CPU host's boot window), **zero genuine assertion failures**.

Re-ran the 8 rounds in **2 waves of 4** (sustainable concurrency per the known host-saturation pattern) → **8/8 rounds 77/77 green**. Ran a second confirmation 2-wave sweep → another **8/8 rounds 77/77 green**. 16 sustainable-concurrency rounds green, no failure union. The implementation + tests are robustly correct; the 8-way errors were purely environmental. Final `results.{1..8}.json` from the green 4-way sweep are preserved in `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-06-28T16:34:46.000Z

**Outcome: ZERO edits.** `PRD_FINALIZED.md` is byte-identical to `PRD.md` (309 → 309 lines, 0% delta). Both `<step_7_diff>` fix categories were pure test bugs where PRD.md already uniquely pins the behavior the implementation exhibits.

- **Category 1 (missing `expected_status=201` — 14 test fixes):** PURE TEST BUG. PRD §220 states verbatim that creates return 201 and modify/transition/admin return 200. All 11 create endpoints in `implementation/` return 201; every modify/transition/list/admin returns 200. PRD already pins 201 for creates; the tests just defaulted to expecting 200. No PRD silence, no mismatch.
- **Category 2 (overfulfillment vs invalid-state precedence — 2 test fixes):** PURE TEST BUG. `routes/sponsors.py:record_contribution` checks state∈{PLEDGED,PARTIALLY_FULFILLED}→ERR_INVALID_STATE, then OCC version, then overfulfillment, matching PRD §216 fixed priority (INVALID_STATE pri 5 → stale-version pri 6 → OVERFULFILLMENT pri 17) and §3.8 transition origins. A FULFILLED sponsor has no defined contribution transition → ERR_INVALID_STATE. The old test setups wrongly expected ERR_OVERFULFILLMENT from a FULFILLED sponsor. PRD already pins this precedence; no edit warranted.

Mandatory pre-edit enumeration was still performed for both subjects (status-code path across all `routes/` create/modify endpoints; sponsor error-precedence cascade in `routes/sponsors.py` + §216 + §3.8) — both confirmed PRD-consistent with all enumerated impl paths, so no wording change. A zero-edit `PRD_FINALIZED.md` is the correct outcome — no genuine PRD silence or mismatch behind either Step 7 fix.

## Step 9: Complete PRD — 2026-06-28T16:37:00.000Z

**File sizes:** PRD_FINALIZED.md = 309 lines / 48049 chars → PRD_COMPLETED.md = 309 lines / 48874 chars (char-delta **+825**; 5 lines revised in place, no lines added/removed).

**Counts:** ambiguity-pins = **3**, mismatch-revisions = **2** (total 5 changes). All 5 independently verified by orchestrator against impl source.

**Changes:**
- §2.1 User and RBAC — insert — ambiguity — named the unauthenticated health probe as `GET /_health`, requiring no headers and returning `200 OK` with an empty `data` object (PRD was silent on path/method/response) — `routes/system.py:15-18` (verified).
- §3.2 Memberships and ASTC Reciprocity — insert — ambiguity — pinned the astc-status read shape: returns the full membership view (incl. `astc_eligible`) plus a boolean field `astc_reciprocal_admit` carrying the determination (PRD said only "reports this determination," naming no field) — `routes/memberships.py:131-139` + `services/calculations.py:128` (verified).
- §3.3 Scheduling and Running a Show — revise — mismatch — `seats_sold` definition narrowed wrongly to "namely those in `HELD` or `CONFIRMED`"; impl also adds the `total_seats` of every `DEPOSIT_PAID` GroupBooking on the show — `services/show_logic.py:10-26` (also `routes/group_bookings.py:98-120`) (verified).
- §3.3 Scheduling and Running a Show — insert — ambiguity — on completion `seats_sold` is recomputed, so a completed show's `seats_sold` reflects only the remaining `CONFIRMED` seats (PRD was silent on this observable field at completion) — `routes/shows.py:181-200`.
- §3.6 Camps, Classes, and the Waitlist — revise — mismatch — PRD pinned a `version` bump only on the enrolled path, leaving the waitlist path ambiguous; impl does **not** bump the session `version` for a waitlist add (session/`enrolled_count` untouched), which matters for subsequent OCC — `routes/registrations.py:99-106`.

**Cross-references checked (no change needed):** `fulfillment_ratio` returned as float/`0.0` (PRD §2.9/§3.8 already covers); validation-priority ordering in create_show/create_rental/create_booking matches §3.10; `activate` source states (PENDING/EXPIRED) already pinned by §3.2; group-booking confirm leaving seats out of `seats_sold` once CONFIRMED consistent with corrected DEPOSIT_PAID-only rule. Tests used only as auxiliary cross-reference, not authority.

---

## Pipeline Complete — 2026-06-28T16:37:00.000Z

All 9 steps executed end-to-end. Final state: **77/77 tests passing across 16 sustainable-concurrency stability rounds** (two independent 2-wave sweeps). Task directory contains SCAFFOLD trio, worklog.md, test_helpers/ (9 files), test_suite/ (conftest + 9 test files, 77 tests), and workspace/ with INSTRUCTION.md, PRD.md, PRD_FINALIZED.md (zero-edit), PRD_COMPLETED.md (5 edits), and a working Flask implementation/ with start.sh + preserved results.{1..8}.json (all green).
