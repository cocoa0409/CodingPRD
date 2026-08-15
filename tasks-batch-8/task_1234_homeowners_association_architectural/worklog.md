# Worklog — task_1234_homeowners_association_architectural

## Step 1: Create task directory — 2026-08-12T03:54:00.000Z

Task directory pre-assigned as `tasks/task_1234_homeowners_association_architectural` with `workspace/` subdirectory; both already exist. Step 1 auto-index scan skipped per instruction.

## Step 3: Copy shared files — 2026-08-12T03:55:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1234_homeowners_association_architectural/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-08-12T04:37:00.000Z

## Scaffold generated: task_1234_homeowners_association_architectural

**Complexity profile** (harder-than-expert calibration):
- Primary archetype: `compliance_audit`; secondary: `multi_party_negotiation` (committee quorum voting + board appeal with segregation-of-duties)
- Complexity layers (4): `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`
- Structural dimensions: hierarchical topology, cyclic state-machine shape (revision loop + re-inspection loop + posture-driven gating on Property), one_to_many + cross_aggregate relationships, `segregation_of_duties` role model (CommitteeMember/BoardMember/ Homeowner all `entity_backed:Owner`; SoD checks on applicant-vote and voter-appeal-decide), immediate consistency

**Surface counts:**
- Entities: 14 (Association, Owner, Property, Application, Attachment, CommitteeVote, Appeal, ConstructionPermit, BlackoutPeriod, Inspection, Violation, Fine, Lien, Variance)
- Endpoints: 55 (incl. `POST /arc/_clock/set_current_utc` with pinned startup default 2026-05-01T00:00:00Z, and `POST /arc/_sweeps/daily` ops checkpoint with fixed 5-step order)
- Error codes: 29
- State machines: 8 (Application cyclic with deemed-approval auto-transitions; Appeal; ConstructionPermit; Inspection cyclic; Violation; Fine; Lien; Property posture-driven compound)
- Calculations: 5 (statutory_deadline_check [dual-variant CALENDAR/BUSINESS], quorum_decision_tally [mode-a combinatorial, supermajority flag + abstain exclusion], fine_accrual [dual-variant SIMPLE/TIERED + per-day rounding pinned], property_outstanding_balance [mode-b rounding-order aggregation], window_conflict_detection [half-open permits vs closed blackouts])
- Validations: 12 priority rows (auth → role → existence → shape → ownership/SoD → state → safety/posture → temporal → constraint → referential → fiscal → OCC)
- OCC rules: 2 (`amend-conditions-stale-application`, `contractor-change-stale-permit`, both ERR_STALE_VERSION/412)
- §1.8 difficulty instances: 18 (2 per rule, all §0.5 differentiation clauses honored; all formula-derived asserts pre-computed as literals, e.g. tiered 17000 vs simple 15000, per-day rounding 1500 vs forbidden 1499, quorum 3/5 flip, deadline 05-06 vs 05-08)
- §1.9 corner instances: 46 total (38 active + 8 excluded_because stubs), spanning all nine claim-extraction sections
- Test-recipe replay: 763 calls across both design files; my own audit script additionally verified grounds resolvability, cross-file name uniqueness, `${var}` placeholder closure, stub target existence, forbidden-vocabulary absence, and OCC wiring — all clean

**Lint verdict (verbatim):**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_1234_homeowners_association_architectural/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_1234_homeowners_association_architectural/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_1234_homeowners_association_architectural/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     38
  Calls scanned (§1.8+§1.9):  763

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files on disk (all three confirmed):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1234_homeowners_association_architectural/SCAFFOLD.yaml` (§1.0–§1.7 only, no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1234_homeowners_association_architectural/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1234_homeowners_association_architectural/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

Two lint iterations were needed: initial run flagged 2 missing FK reverse-reachability GETs (`GET /arc/applications/{id}/variances`, `GET /arc/permits/{id}/violations`), which were added; second run clean. No sibling task directories were inspected at any point.

## Step 4: Generate PRD — 2026-08-12T04:51:00.000Z

**Task 1234 PRD generation — complete**

**Output file (confirmed on disk):** `/home/ubuntu/github/CodingPRD/tasks/task_1234_homeowners_association_architectural/workspace/PRD.md` — 52,356 bytes, 337 lines, 7,379 words.

**Section outline:**
- §1 Introduction (2 paragraphs: business context + statutory deemed-approval risk angle)
- §2 Global Specifications: 2.1 RBAC (5 roles, identity prose per role: Manager/Inspector opaque, Homeowner/CommitteeMember/BoardMember entity-backed by Owner), 2.2 API Response Structure (verbatim block, byte-for-byte verified), 2.3 Pagination (limit 10/1/100, offset 0, created_at ascending), 2.4 Resource Identity/Timestamps/Versioning, 2.5 Property Compliance Ledger (balance sum, posture derivation order LIENED→FINES_OUTSTANDING→CLEAR, fine invariant), 2.6 Statutory Timekeeping & Logical Clock (CALENDAR/BUSINESS, sweep fixed 5-step order), 2.7 Monetary Precision (integer cents, basis points, per-day round-half-up then accumulate), 2.8 Construction Windows & Calendar Semantics (half-open vs closed intervals, adjacency asymmetry), 2.9 Validation Order & Error Precedence (all 12 priorities with 8a/8b/8c, 9a/9b/9c, 11a/11b/11c sub-orders and applies_to sets), 2.10 OCC (both rules), 2.11 Nested Resource Retrieval (left-to-right, all 11 NOT_FOUND ids)
- §3 Business Logic (8 subsections): 3.1 chartering/config/owners/properties, 3.2 blackout calendar + variance registry, 3.3 drafting/submitting applications, 3.4 committee review/ballots/tally/decision, 3.5 statutory clock/deemed approval, 3.6 denial/board appeal, 3.7 permits/contractors/extensions/inspections, 3.8 violations/fines/remediation/liens/sweep
- §4 Endpoint table: 55 rows, 4 columns (Method, Path, Description, Authorized Role(s))
- §5 Error catalogue: 29 rows, 2 columns

**Scaffold render locations:** entities/defaults → 3.1–3.3, 3.7, 3.8; state machines → 3.3–3.8 (Application, Appeal, Permit, Inspection, Violation, Fine, Lien) with posture machine summarized in 3.8; calculations → 2.5/2.7/2.8 (pinned semantics) + 3.4 (tally), 3.5 (deadline), 3.8 (accrual with worked 17000-vs-15000 example), 3.4/3.6/3.7 (window conflict); validations → 2.9 in full plus trigger-side prose in §3; concurrency rules → 2.10 + 3.4/3.7; endpoints → §4; errors → §5; roles → 2.1.

**Contract reports:**
- Contract 1 (field coverage): 92/92 entity fields, 12/12 endpoint-input identifiers (incl. `revision_notes`, `denial_reason`, `outcome`, `new_window_end`, `expected_application_version`, `expected_permit_version`, `amount_cents`, `to_iso8601`, `result`, `remediation_note`), 6/6 sweep/clock output fields, query params (`limit`, `offset`, `status`, `kind`, `guideline_section`) — 0 missing. PASS (two passes run; pass 1 caught `ballot`/`permit_id`/`property_id`, repaired in place).
- Contract 2 (rule coverage): 12/12 validation priorities with explicit ordering prose; 2/2 OCC rejections (write operation + expected-version field + `ERR_STALE_VERSION`/412); all state transitions incl. both DEEMED_APPROVED sources, EXPIRED→COMPLETED late completion, FAILED_REMEDIATION→SCHEDULED re-inspection loop, and all 4 posture transitions; 5/5 calculations with constants/precision and both variant pairs (supermajority on/off with the 3-approvals-2-denials divergence, simple vs tiered with worked cents example); 29/29 error IDs matched to trigger prose; all cascades expressed (permit creation, fine creation, posture recompute, late-completion remediation, expiry). Sibling branches (approve/deny, UPHELD/OVERRULED, PASS/FAIL, settle from ACCRUING and STOPPED, waive on ACCRUING and STOPPED) rendered at equal density. PASS.
- Contract 3 (§3 path purity): 430 backtick tokens scanned, 0 path tokens, 0 bare HTTP methods, 0 method+path combos. PASS.

**Zero-silence decisions (rules pinned explicitly):** `submitted_at` stamped once on first submit, never restamped; deemed approval performs no window validation (contrasted with committee/appeal approvals); exact two-thirds approves, tie denies under plurality, integer-form comparison (3A ≥ 2(A+D), A+D > 0, abstentions excluded); tier boundary inclusive (day index equal to `grace_days_snapshot` stays at base rate); rounding pinned per-day-then-sum with the reverse order forbidden; blackout-closed vs permit-half-open asymmetry (window starting on blackout end date conflicts; touching permit windows do not); expiry requires current date later than `window_end` AND no PASSED inspection; lien auto-file requires balance at-or-above threshold AND oldest-unpaid-fine age at least `lien_min_age_days` AND no existing FILED lien; settle exact-amount, waiver at-most-outstanding; `applicant_hold_days` counts whole days after revision-request date through resubmit date inclusive; appeal window measured as whole days after `decided_at` through filing day; recast replaces ballot and bumps `recast_count` (one row per voter invariant); only conditions-amend and contractor-change carry expected-version fields; logical clock default 2026-05-01T00:00:00Z with no wall-clock fallback; temporal checks (priority 8) explicitly outrank quorum/completeness (priority 9) when multiple checks fail on decide; empty-string semantics for violation `application_id`/`source_inspection_id`/`source_permit_id` on manager reports; 1:1 fine-per-violation and 0-or-1 permit-per-application cardinalities stated.

**Constraint compliance:** the two forbidden design-index files were never opened; no sibling task directories were inspected.

## Step 5: Generate unit tests — 2026-08-12T05:19:00.000Z

## Task 1234 (HOA Architectural Review) — test generation summary

**Test counts**
- Queue A (Difficulty/§1.8): **18/18 instances translated, 36 tests** (exactly 2 per instance, all tagged `Design: Difficulty/<rule_id>/<instance.name>`).
- Queue B (Corner/§1.9): **38/38 non-stub instances translated, 38 tests** (1 per instance, tagged `Design: Corner/<section>/<instance.name>`). All **8 `excluded_because:` stubs** left untranslated; every stub's `difficulty_instance` cross-reference verified to resolve to a real §1.8 instance name.
- **Total: 74 tests, 0 instances skipped.** Every instance passed the PRD-first two-condition filter (verbatim coverage + unique derivability). One deliberate calibration: the PRD (§2.4) says version "increments by one on every mutation" but never pins the initial value, so all version assertions are relative (`v == captured + N`) rather than the design indices' absolute literals (e.g. `== 7`, `== 1`); the OCC pair asserts the full success/replay semantics with relative versions. No `skip`/`skipif`/`xfail` markers anywhere.

**Verification performed**
- `py_compile` on all 19 files: clean.
- `pytest --collect-only`: **74 tests collected**, no import errors (all `test_helpers` imports resolve).
- Tag audit: each test has exactly one terminal `Design:` line; all 56 distinct tags resolve to real instances; queue A ≥2/instance and queue B ≥1/non-stub instance confirmed programmatically; no stub tagged.
- PRD citation audit: 127 quoted fragments (≥6 words, split on ellipses) extracted from docstrings — **all verbatim substrings of `workspace/PRD.md`**.
- Scaffold-leak scan (`scaffold`, `Table N`, `§1.x`, `SCAFFOLD_`): zero hits in generated code.
- `pyflakes`: no undefined names (only barrel/star-import noise).

**File layout**
- `test_helpers/` (9 files): `types.py` (14 TypedDicts + 13 enums, all entities common-fields-true), `api_client.py` (52 endpoint methods on `GenericApiClient`), `api_errors.py` (28 error ids + status map registered via `set_error_http_status_map`), `assertions.py` (per-entity asserts + `assert_fine_invariant` + `assert_sweep_report`), `factories.py` (18 payload factories), `constants.py`, `test_users.py` (opaque Manager/Inspector constants + `make_homeowner/committee/board_headers` entity-backed builders, identity threaded everywhere), `fixtures.py` (composite tiers: `setup_review_ready`, `setup_approved_with_permit`, `setup_denied_application`, `setup_violation_with_fine`, `setup_liened_property`, `setup_failed_inspection`, sweep/clock helpers, all via `get_success_data`), `__init__.py` barrel.
- `test_suite/` (10 files): `conftest.py` + `test_01_registry_basics.py` (9) · `test_02_submission_gates.py` (8, incl. lien posture gate pair) · `test_03_committee_tally.py` (10) · `test_04_statutory_clock.py` (5) · `test_05_decisions_appeals_precedent.py` (8) · `test_06_construction_windows.py` (6) · `test_07_inspections.py` (7) · `test_08_enforcement.py` (14) · `test_09_security_rbac.py` (7).

## Step 6: Generate implementation — 2026-08-12T05:19:00.000Z

## Summary — task_1234_homeowners_association_architectural implementation

**File layout** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1234_homeowners_association_architectural/workspace/implementation/`):
- `app.py` — 63,587 bytes, 1,666 lines (entire Flask server: envelope, auth, store, calculations, all routes)
- `start.sh` — 396 bytes, executable
- `requirements.txt` — 14 bytes (`flask>=2.2,<4`)

**Routes**: 55/55 scaffold §1.5 (method, path) pairs registered exactly (Flask route dump shows 56 only because of Flask's built-in `/static` helper; all 55 declared endpoints present, no extras).

**start.sh contract**: `set -euo pipefail`, `cd "$(dirname "$0")"`, guarded dependency install (`if ! python3 -c "import flask"` → `pip install -q -r requirements.txt` only when missing), `exec python3 app.py` foreground; app binds `0.0.0.0:$PORT` (default 10000 via `os.environ.get("PORT", "10000")`), threaded. Verified booting fresh on ports 18901/19002/19003 with HTTP ready in <3s.

**Key behaviors implemented**:
- **Envelope**: `meta.api_request_id` (`req_`+24 hex), `meta.api_request_timestamp` (logical clock, `YYYY-MM-DDTHH:MM:SS.mmmZ`), `response_type` object/array/error, error body `data.error_id`/`data.message`; list meta adds `limit/offset/total_count/has_more` (default 10, clamped [1,100]/[0,∞), created_at-ascending sort).
- **Auth/RBAC**: `X-User-ID`+`X-User-Role` presence + declared-role check → 401 `ERR_UNAUTHENTICATED`; role-not-in-list → 403 `ERR_UNAUTHORIZED`; Homeowner ownership (application.owner_id / property.primary_owner_id) → 403; CommitteeMember/BoardMember applicant-or-prior-voter bars → 403 `ERR_SEGREGATION_OF_DUTIES`.
- **Clock**: in-memory logical clock, boot default exactly `2026-05-01T00:00:00Z`, never wall-clock; `POST /arc/_clock/set_current_utc` returns `current_utc`.
- **State machines**: Application full lifecycle (incl. cyclic revision loop with `applicant_hold_days` accumulation, `submitted_at` first-stamp-only, terminal lockdown), Appeal, ConstructionPermit (incl. EXPIRED→COMPLETED late completion with violation remediation cascade), Inspection (SCHEDULED→PASSED/FAILED_REMEDIATION→SCHEDULED with cross-entity remediation gate), Violation, Fine, Lien, derived Property posture (LIENED > FINES_OUTSTANDING > CLEAR).
- **Calculations**: statutory deadline (CALENDAR/BUSINESS countable days in (submitted, current], minus hold days, fires at `elapsed >= statutory_response_days`); quorum tally (supermajority `3A >= 2(A+D)` with A+D>0, abstain-excluded, exact 2/3 approves; plurality strict `A > D`, tie denies); fine accrual (per-day `Decimal` ROUND_HALF_UP increments then accumulate, tier boundary `k > grace_days`, PRD worked example 10000/1000/grace3/2.0x/5d → 17000 verified); property balance as sum of per-fine outstanding with invariant `accrued == settled + waived + outstanding`; half-open permit overlap (`s<e' && s'<e`, adjacency allowed) vs closed blackout conflict (`s<=be && e>bs`, `window_start == blackout end` conflicts).
- **Validation precedence** per PRD §2.9: auth → role → path-existence (left-to-right, specific 404s) → body shape (required/unknown → `ERR_INVALID_REQUEST`, enum → `ERR_INVALID_ENUM`) → context auth/SoD → state (409) → posture gate (`ERR_PROPERTY_LIENED`) → temporal 8a overlap(409)/8b blackout(422)/8c appeal-window(422) → constraints 9a completeness/9b window-too-long/9c quorum → precedent(422) → fiscal 11a settle-exact/11b waiver-cap/11c lien-zero-balance(409) → OCC last. Notably: decide runs window checks (when tally approves) before the quorum check, so `ERR_WINDOW_OVERLAP` outranks `ERR_QUORUM_NOT_MET` (verified); deny branch skips window checks.
- **OCC**: `expected_application_version` on conditions amend, `expected_permit_version` on contractor-change → 412 `ERR_STALE_VERSION` (both required fields, checked at priority 12 after state).
- **Cascades**: approval/deemed/appeal-upheld → permit creation → `open_permit_count` recompute (deemed approval does no window validation); violation creation (manager report / inspection FAIL / permit expiry) → exactly-one ACCRUING fine with config snapshots → property balance/posture recompute; remediate/late-pass stop fines after bringing accrual current; settle accrues-to-date before the exact-amount check (failure mutates nothing); waive partial on ACCRUING/STOPPED without accruing; sweep order deemed→accrual→escalation→lien-auto-file (balance ≥ threshold AND oldest unpaid fine age ≥ `lien_min_age_days` AND no FILED lien)→permit expiry; sweep idempotent per date via `accrued_through_date` and state gates. Version bumps on every mutation including cascaded ones; property version bumps only when a computed field actually changes.
- **Storage**: pure in-memory dicts, zero seeding at boot (verified: empty sweep returns all-zero counts on fresh process).

**Smoke tests run** (curl/Python harness against live server, 3 fresh boots): 52 + 13 + 20 + 31 + 8 checks passed covering envelope shape, auth errors, CRUD + defaults (grace 0 / 10000bp / lien age 0 / supermajority true / window 90 / remediation 7 / appeal 30), submit gates, recast semantics (1 row/voter, recast_count, cast_at preserved), supermajority vs plurality divergence (3A2D both variants, exact-2/3, all-abstain deny), deemed approval CALENDAR vs BUSINESS (weekend-skipping) with boundary inclusivity, revision-hold clock freezing, window overlap/blackout/adjacency semantics, extension boundaries (exactly max_window_days ok, +1 rejected), OCC 412s, appeal window expiry, SoD on votes/conditions/appeal-decide, tiered accrual math, waive/settle invariant, lien ladder (age gate, threshold, satisfy gate, LIENED blocking submit, LIENED→CLEAR), inspection FAIL cascade + reschedule gate, late completion from EXPIRED with violation auto-remediation, permit expiry sweep, pagination meta/clamping, nested 404 left-to-right. The only failures seen during testing were expectation bugs in my throwaway test scripts (stale clock between scenarios, recast-replaces semantics, blackout-inside-extension), each re-verified against the PRD as correct implementation behavior.

Orchestrator pre-sweep route reconciliation: 55/55 scaffold (method, path) pairs registered in implementation (name-agnostic path-param comparison) — 0 missing, 0 extra.

## Step 7: Run tests and iterate — 2026-08-12T05:35:00.000Z

- **Iterations run:** 1 fix cycle (sweep #2 after fix). Initial state was 72/74 in all 8 rounds; final sweep: **74/74 passed in all 8 rounds, 0 failed, 0 errors**.

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none. Diagnosis confirmed `get_violation_fine(violation_id)` in `/home/ubuntu/github/CodingPRD/tasks/task_1234_homeowners_association_architectural/test_helpers/fixtures.py` is PRD-faithful (PRD §3.8: fines are linked one-to-one to a violation and "listable as an exactly-one-entry collection" via `GET /arc/violations/{id}/fines`).

- **Fixes applied to `test_suite/`:** 2 fixes, both in `/home/ubuntu/github/CodingPRD/tasks/task_1234_homeowners_association_architectural/test_suite/test_08_enforcement.py` — same bug pattern: the test captured `fine_id = bundle["fine"]["id"]` and passed it to `get_violation_fine()`, which expects a **violation** id, producing the 404 `ERR_VIOLATION_NOT_FOUND` in setup. Changed to `violation_id = bundle["violation"]["id"]` in:
  1. `TestPerDayRoundingOrder::test_each_single_day_adds_the_rounded_increment` (line ~108)
  2. `test_fine_tier_boundary_grace_day_exact` (line ~246)

  Both tests' assertions trace verbatim to PRD §3.8/§2.7 (per-day rounding order, grace-day boundary); only the setup id reference was wrong. Every other test in the file already used `bundle["violation"]["id"]` correctly.

- **Fixes applied to `implementation/`:** none. The implementation correctly returned `ERR_VIOLATION_NOT_FOUND` for the fine-id-as-violation-id lookup; no PRD-required behavior was changed.

Orchestrator verification: all 8 `results.{1..8}.json` on disk show passed=74/74, failed=0, errors=0.

## Step 8: Finalize PRD — 2026-08-12T05:32:00.000Z

**Step 8 result: PRD_FINALIZED.md produced as a byte-identical copy of PRD.md (zero edits).**

**Line counts / %-delta:** PRD.md 336 lines, PRD_FINALIZED.md 336 lines — 0.0% delta; `cmp` confirms byte-identical.

**Changes made:** none.

**Why each `<step_7_diff>` item required no PRD change:**

- **Test fix 1 — `TestPerDayRoundingOrder::test_each_single_day_adds_the_rounded_increment` (test_suite/test_08_enforcement.py:104-116):** Pure test setup bug. The test captured `bundle["fine"]["id"]` and passed it to `get_violation_fine()`, which expects a violation id. The assertion (per-day rounding order: 333-cent daily rate, 15000 bp multiplier → 500/1000/1500 accrued) traces verbatim to PRD §3.8 (PRD.md:226, "rounding each day's increment before adding it into `accrued_cents` — never summing raw amounts and rounding once, per §2.7"). No PRD silence: the per-day rounding order is already pinned.

- **Test fix 2 — `test_fine_tier_boundary_grace_day_exact` (test_suite/test_08_enforcement.py:233-256):** Same bug pattern (fine id passed where violation id expected). Assertions trace verbatim to PRD §3.8 (PRD.md:226, "a day whose index is at most `grace_days_snapshot` still adds the base `daily_rate_cents` — the grace day itself included — while a day whose index exceeds the grace count adds the escalated increment"). No PRD silence.

- **Underlying endpoint semantics (the fine-id-as-violation-id 404):** Already fully pinned by the PRD in three places:
  - PRD §3.8 (PRD.md:222): "exactly one fine is created for the violation — they are linked one-to-one by the fine's `violation_id`, and the fines of a violation are listable as an exactly-one-entry collection".
  - PRD §4 endpoint table (PRD.md:294): `GET /arc/violations/{id}/fines` — "List fines of a violation (exactly one entry)"; the path template itself places the identifier under `/arc/violations/`, making it a violation id.
  - PRD path-existence rule (PRD.md:127): "path template identifiers resolve to existing resources, validated left to right; the first unresolved identifier yields its specific 404 — … `ERR_VIOLATION_NOT_FOUND`, `ERR_FINE_NOT_FOUND`…".

- **Implementation behavior confirmed consistent with PRD:** `implementation/app.py:1456-1460` (`list_violation_fines`) resolves the path id via `get_violation(vid)` (app.py:308-312), which raises `ERR_VIOLATION_NOT_FOUND` for any unknown id — exactly what the buggy test observed, and exactly what the PRD path-existence rule requires. The fixture docstring at test_helpers/fixtures.py:143-149 cites PRD §3.8 and is PRD-faithful.

- **Step 7 made zero implementation changes and zero test deletions;** both fixes were confined to test setup id references. No impl-pinned behavioral choice exists that the PRD leaves open, and no PRD/impl mismatch was revealed.

**Pre-edit search log:** no edits were committed, so no wording searches were triggered. Verification reads performed: `test_helpers/fixtures.py:135-160` (get_violation_fine signature/contract), `test_suite/test_08_enforcement.py` (both fixed tests, all `get_violation_fine` call sites — every other test already used `bundle["violation"]["id"]`), `PRD.md:107,127,214,220-238,294` (§3.8 fine semantics, endpoint table, path-existence rule), `implementation/app.py:306-312,1456-1467` (violation lookup + fines listing routes).

**Artifact:** `/home/ubuntu/github/CodingPRD/tasks/task_1234_homeowners_association_architectural/workspace/PRD_FINALIZED.md` (byte-identical copy of PRD.md).

## Step 9: Complete PRD — 2026-08-12T05:39:00.000Z

PRD_COMPLETED.md produced at /home/ubuntu/github/CodingPRD/tasks/task_1234_homeowners_association_architectural/workspace/PRD_COMPLETED.md.

**Source vs output:** PRD_FINALIZED.md (336 lines / 52356 chars) → PRD_COMPLETED.md (337 lines / 54589 chars), char-delta +2233. Diff: 17 hunks, all inline inserts/revisions; no new sections, no deletions.

**Counts:** 16 ambiguity-pins, 0 mismatch-revisions (implementation matched every behavior the PRD already pinned — validation order, tally formulas, accrual rounding, window/blackout semantics, sweep order, cascades, response codes, role tables all verified line-by-line against app.py).

**Changes:**
- §2.2 Error format — insert — ambiguity — unmatched route/method and server failures return the error envelope with `ERR_INVALID_REQUEST` at 404/405/500 — app.py:99-111
- §2.3 Pagination — revise — ambiguity — non-integer limit/offset fall back to defaults, out-of-range values clamped, not rejected — app.py:352-366
- §2.3 Pagination — revise — ambiguity — creation-timestamp ties broken by insertion order; `has_more` = (offset + returned items) < total_count — app.py:152-153, 81
- §2.4 Versioning — revise — ambiguity — `version` starts at 1 on creation — app.py:137
- §2.9 step 4 — insert — ambiguity — body must be a JSON object (non-object → ERR_INVALID_REQUEST; absent/null treated as empty); enum query filters with undeclared members yield ERR_INVALID_ENUM — app.py:246-254, 375-382
- §3.1 Properties — insert — ambiguity — unresolvable `primary_owner_id` rejected with ERR_OWNER_NOT_FOUND — app.py:676
- §3.2 Blackouts — revise — ambiguity — end_date before start_date → ERR_INVALID_REQUEST (400); omitted `reason` defaults to empty string — app.py:716-722
- §3.2 Variances — insert — ambiguity — unresolvable `application_id` → ERR_APPLICATION_NOT_FOUND before the precedent check — app.py:748-750
- §3.3 Application creation — insert — ambiguity — `requested_window_end` must be strictly later than start, else ERR_INVALID_REQUEST (400); unresolvable `owner_id` → ERR_OWNER_NOT_FOUND — app.py:805-810
- §3.4 Decision — insert — ambiguity — omitted `conditions` defaults to empty list; omitted `denial_reason` defaults to empty string — app.py:1066, 1072
- §3.7 Extension — revise — ambiguity — Homeowner extension right pinned to application's `owner_id` == X-User-ID (not property primary owner) — app.py:1231-1232
- §3.7 Extension — insert — ambiguity — `new_window_end` not later than current `window_end` → ERR_INVALID_REQUEST (400), checked before temporal and length checks — app.py:1238-1240
- §3.7 Record/PASS — insert — ambiguity — late pass moves permit-sourced violations to REMEDIATED with `remediated_at` stamped — app.py:1320-1322
- §3.7 Record/FAIL — insert — ambiguity — created CONDITION_BREACH violation also binds `application_id` to the permit's application; description = result_notes or "Inspection failed" — app.py:1331-1337
- §3.7 Permit expiry — insert — ambiguity — INCOMPLETE_CONSTRUCTION violation also binds `application_id` of the permit's application — app.py:1657-1660
- §3.8 Violation report — insert — ambiguity — supplied non-empty `application_id` that doesn't resolve → ERR_APPLICATION_NOT_FOUND — app.py:1384-1385
- §3.8 Settlement — insert — ambiguity — settle requires caller to be the violation property's `primary_owner_id`, else ERR_UNAUTHORIZED — app.py:1471-1473
