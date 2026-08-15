# Worklog — task_1897_reserve_study_capital_reserve_funding

## Step 1: Create Task Directory — 2026-08-14T23:38:00.000Z

Pre-existing: tasks/task_1897_reserve_study_capital_reserve_funding/ and workspace/ already created by the invoking pipeline; verified, no action taken.

## Step 2: Generate Scaffold — 2026-08-15T00:17:00.000Z

All three scaffold artifacts are generated, lint-clean, and saved. Final report:

## Task 1897 — Reserve Study & Capital Reserve Funding: scaffold complete

**Files written** (no sibling task was inspected — design is purely from the scenario + skill spec):

- `/home/ubuntu/github/CodingPRD/tasks/task_1897_reserve_study_capital_reserve_funding/SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1897_reserve_study_capital_reserve_funding/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key, 18 instances (2 per rule)
- `/home/ubuntu/github/CodingPRD/tasks/task_1897_reserve_study_capital_reserve_funding/SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key, 39 instances (29 active + 10 `excluded_because:` stubs)

**Design summary**
- **Profile**: ledger_reconciliation (primary) + compliance_audit (secondary); layers: dual-variant calculation, ops-run checkpoint (annual update), derived-field reconciliation, OCC. Flat topology (8 peer entities with FK links), cyclic state shape, approval-chain roles (ReserveSpecialist → BoardMember, plus AssociationManager and PlatformAdmin; all `identity: opaque`).
- **Entities (8)**: Association, StateReserveRule, ReserveStudy, Component, FundingPlan, SiteVisit, Expenditure (two independent state axes: approval × reconciliation), Disclosure.
- **Endpoints (35)**, **errors (25)**, **calculations (9)** — including the tri-variant contribution solve (BASELINE/THRESHOLD/FULL floors with minimal-integer-cents bisection), chronological vs forward-looking expenditure variance, largest-remainder disclosure allocation, annual RUL rolldown, site-visit cadence/gap, and special-assessment projection.
- **OCC**: one true-race rule (`plan-create-stale-study`) on `ReserveStudy.version` guarding create-with-supersede plan creation; logical clock endpoint with the mandated `2026-08-01T00:00:00Z` default.
- **Rule coverage highlights**: cascades of depth 3 (approve → cash debit → percent recompute → compliance flip) and depth 2 (adopt → supersede → plan retire + disclosure void); priority conflicts on state-vs-fiscal and temporal-vs-constraint; boundaries at percent-funded == 50.00 (cash 5000 vs 4999) and 30-day visit gap; half-open fiscal-window overlap vs point-plus-buffer visit gap; cash-conservation (approve+reverse) and component-cardinality conservation (retire+restore).

**Verification**
- All formula-derived asserts were pre-computed by executing the pinned formulas in Python: BASELINE 28825 / THRESHOLD 31820 (floor 123964) / FULL 33077 for the F1 fixture; allocation shares 25743/25742 summing exactly to 51485; forward variance 90909 vs chronological 100000; analysis shortfall −597833 first hit FY2028; post-rolldown FFB 130000 / 384.62%.
- `scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (536 calls scanned.)
- Additional self-audit script confirmed: every `${var}` placeholder is bound by an earlier `captures:` in its instance, and none of the forbidden concurrency vocabulary appears in any file.

One repair cycle was needed during authoring: YAML flow mappings can't contain bare `$.data[N]` JSONPaths or `errors[...]` grounds refs (fixed by quoting), and lint check (f) required literal `{id}` placeholder segments in sub-resource paths plus a `GET /reserve-studies` filtered list for the `adopted_plan_id` FK (endpoint count 34 → 35).

## Step 3: Copy Shared Files — 2026-08-15T00:18:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1897_reserve_study_capital_reserve_funding/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-15T00:33:00.000Z

PRD generation complete. Output written to `/home/ubuntu/github/CodingPRD/tasks/task_1897_reserve_study_capital_reserve_funding/workspace/PRD.md` (295 lines). The withheld design-index files were never opened.

**Document structure** (skeleton designed from the domain, per the diversity rules):
- §1 Introduction — 2 paragraphs, business-context angle (special-assessment avoidance, statutory variance by state).
- §2 — 11 subsections: RBAC (2.1), the byte-verbatim response envelope (2.2), pagination (2.3), then domain-derived cross-cutting concerns: the logical clock (2.4), fiscal calendars and half-open study windows (2.5), cents/percents/round-half-up precision (2.6), common resource properties (2.7), the 11-tier validation-precedence cascade (2.8), OCC on plan creation (2.9), derived-total propagation and the compliance posture (2.10), nested path resolution (2.11).
- §3 — 9 subsections organized by business timeline: statutory onboarding (3.1), site-visit cadence (3.2), component inventory and the fully funded balance (3.3), the 30-year contribution solve with BASELINE/THRESHOLD/FULL floors (3.4), board review and the revision loop (3.5), expenditure approval with dual CHRONOLOGICAL/FORWARD_LOOKING variance reconciliation (3.6), disclosures and the largest-remainder allocation waterfall (3.7), the annual-update rolldown (3.8), special-assessment risk projection (3.9).
- §4 — 35-row endpoint table (4 columns only); §5 — 24-row error catalogue (2 columns only).

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields + endpoint inputs/query/path params: 67 required, 67 present, 0 missing (verified mechanically, two passes)
Status: PASS

Rule coverage check:
- validations[] priority tiers: 11 checked, 11 expressed as an ordered cascade in §2.8, 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (POST /reserve-studies/{id}/funding-plans + expected_study_version + ERR_STALE_VERSION/412, no race framing), 0 missing
- state_machines[].transitions: 22 checked, 22 fully expressed (preconditions + error IDs + side effects), 0 missing
- calculations[]: 9 checked, 9 fully expressed in precise prose (no pseudocode, no fuzzy words — mechanically scanned), 0 missing
- validations[] conditions: 25 error IDs checked, 25 matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: 35 endpoints checked, all side effects and guard scopes expressed, 0 missing
- entities[].fields[] structured content: defaults/initials/nullability reconstructible from prose, 0 missing
- sibling-branch symmetry: 4 groups checked (plan-type floors, CHRONOLOGICAL/FORWARD_LOOKING variants, cadence study types, optional reason fields), 4 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 358
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional contract-precision verifications: §2.2 confirmed byte-identical to `section-2.2-response-structure.md` (including `req_RANDOMALPHANUM123456` and the empty `"data": { }`); pagination defaults/min/max and `created_at` ascending sort stated; all 42 enum/state values and all 4 role names appear verbatim; the document ends at §5 with no audit footer. One repair was made during the walk: the `SUBMITTED → DRAFT` study rejection now explicitly reverts both `SELECTED` and `RECOMMENDED` plans to `DRAFT`, matching the FundingPlan machine's `RECOMMENDED → DRAFT` system trigger.

## Step 5: Generate Unit Tests — 2026-08-15T00:52:00.000Z

All audits pass. The generation is complete. Final state of the deliverables:

**Stage 1 — `test_helpers/`** (at `/home/ubuntu/github/CodingPRD/tasks/task_1897_reserve_study_capital_reserve_funding/test_helpers/`):
- `types.py` — 8 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version` per PRD §2.7) + 14 enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (incl. `/_clock/set_current_utc`)
- `api_errors.py` — all 25 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions plus `line_share_cents()`, which extracts an allocation line's share name-agnostically (the PRD pins allocation values/order but never names the per-line keys — this keeps the literal assertions two-reader-safe)
- `factories.py`, `constants.py` (RULE_CA/NV/TX, F1 inventory, gap/horizon/tolerance constants), `test_users.py` (4 opaque roles, shared constants are canonical — no entity-backed roles exist), `fixtures.py` (seed/onboard/visit/study/plan primitives + `setup_draft/submitted/adopted_study` composites with separate `association_overrides` channel), `__init__.py` barrel

**Stage 2 — `test_suite/`**: `conftest.py` + 9 concern-grouped files holding **75 tests**:
- `test_01_foundations_access_and_onboarding.py` (11), `test_02_component_inventory.py` (9), `test_03_funding_plans.py` (9), `test_04_site_visits.py` (5), `test_05_study_submission.py` (8), `test_06_study_adoption_and_revision.py` (10), `test_07_expenditure_approval.py` (11), `test_08_reconciliation_and_compliance.py` (6), `test_09_disclosures_updates_analysis.py` (6)

**Verification results:**
- **Coverage**: every one of the 18 §1.8 difficulty instances has ≥2 tests; every one of the 39 non-stub §1.9 corner instances has ≥1 test. All 17 `excluded_because:` stubs left untranslated; all stub cross-references resolve to real instances.
- **C4 tags**: all 75 docstrings end with exactly one `Design: Difficulty/...` or `Design: Corner/...` line, each resolving to a real instance `name:`.
- **C1/C2/C3 citations**: all 105 long quoted segments (≥8 words) survive literal grep of `PRD.md` (whitespace-normalized); initial elided quotes were rewritten to full verbatim sentences.
- **No skips**: zero `skip`/`skipif`/`xfail`; no "scaffold" mentions in generated code; `py_compile` and `pytest --collect-only` (75 collected) clean.

**Key design decisions:**
- Priority-pair instances (state-beats-fiscal, cadence-beats-content) were translated as dual-failure tests because PRD §2.8 ("an earlier failure masks all later checks") and §3.5 ("in this order of narrative priority") explicitly state the ordering — not silence-pattern violations.
- Second tests per difficulty instance assert the same instance's PRD-covered claims from a complementary angle (e.g. reverse-restores-compliance for the approve cascade; distributed-disclosure-survives-supersession for the adoption cascade; zero-schedule floor collapse for the THRESHOLD solve).
- No instances were skipped: every non-stub instance had both verbatim PRD coverage and unique derivability.

## Step 6: Generate Implementation — 2026-08-15T00:52:00.000Z

The implementation is complete. Here is a summary of what was built:

## Implementation Summary

**Location**: `/home/ubuntu/github/CodingPRD/tasks/task_1897_reserve_study_capital_reserve_funding/workspace/implementation/`

### File Structure
- **`start.sh`** -- Executable launcher; guards pip install with `python3 -c "import flask"` check; runs `exec python3 app.py` in foreground
- **`requirements.txt`** -- Flask dependency
- **`app.py`** -- Flask entry point; registers all blueprints; error handlers for ApiError, 404, 405, 400, 500; listens on `PORT` env var (default 10000), binds `0.0.0.0`
- **`db.py`** -- In-memory store with all entity dicts, logical clock (defaults to 2026-08-01T00:00:00Z), common field generation (id/created_at/updated_at/version)
- **`errors.py`** -- ApiError class, all 25 error ID constants with correct HTTP status codes from the scaffold
- **`response.py`** -- Response envelope helpers producing the exact `meta`/`response_type`/`data` structure; pagination fields in meta for list endpoints
- **`middleware.py`** -- Auth: validates `X-User-Role` header against 4 declared roles; `require_roles()` for RBAC enforcement

### Services Layer (`services/`)
- **`fiscal.py`** -- Fiscal year derivation (calendar-year and non-calendar-year), study window computation (half-open intervals), window overlap check
- **`calculations.py`** -- All calculation rules:
  - FFB computation (per-component round-half-up, then sum)
  - Percent funded (2dp round-half-up, pinned to 100.00 when FFB=0)
  - 30-year replacement schedule (per-event round-half-up)
  - Funding plan solve (binary search over [0, 10^12], three floor variants: BASELINE=0, THRESHOLD=0.5*max O_y, FULL=projected FFB_y)
  - Expenditure variance (chronological + forward-looking)
  - Disclosure allocation lines (floor-then-largest-remainder)
  - Special assessment analysis
  - Compliance re-evaluation

### Routes (`routes/`)
- **`state_rules.py`** -- POST /state-reserve-rules (PlatformAdmin only, uniqueness on state_code)
- **`associations.py`** -- POST /associations, GET /associations/{id}, POST /associations/{id}/annual-update (with RUL rolldown, ANNUAL_STATEMENT disclosure creation, compliance re-eval)
- **`studies.py`** -- Full CRUD + submit/adopt/reject/withdraw + special-assessment-analysis; supersedes prior ADOPTED study on adopt; creates ADOPTION_SUMMARY disclosure
- **`components.py`** -- POST/GET/PATCH + retire/restore; all mutations require DRAFT study and recompute study totals
- **`funding_plans.py`** -- POST with OCC (expected_study_version), recommend, select; same-type plan supersede/lock logic
- **`site_visits.py`** -- POST with 30-day gap enforcement, complete; recomputes next_site_visit_due_date
- **`expenditures.py`** -- POST/GET/list + approve/reject/reverse/accept-variance; full cascade on approve/reverse (cash, component RUL, study recompute, compliance re-eval); live forward variance on read
- **`disclosures.py`** -- List with allocation_lines computed on read; distribute with is_late computation
- **`clock.py`** -- POST /_clock/set_current_utc (PlatformAdmin only)

### Key properties verified
- Boots cleanly from fresh process with empty state (no seeding)
- `start.sh` contract works (PORT env var, 0.0.0.0, foreground, exec)
- All 33 endpoints implemented with correct RBAC
- Response envelope matches scaffold exactly (meta/response_type/data, pagination fields in meta)
- Error envelope matches (error_id/message in data, no pagination fields)
- All validation priorities enforced in order
- OCC on funding-plan creation (ERR_STALE_VERSION 412)
- All state machines implemented with preconditions and side effects
- All calculations use Decimal with ROUND_HALF_UP (no float for money)
- Logical clock defaults to 2026-08-01T00:00:00Z, never falls back to wall-clock
- Clean state on every boot (verified)

## Step 7: Run Tests and Iterate — 2026-08-15T01:05:00.000Z

All 8 parallel rounds pass: 75/75 tests in every round, zero failures, zero flakiness.

## Summary

**Iterations run:** 2 sweeps (16 round-runs total). Sweep 1: 5 tests failing in all 8 rounds (consistent, not flaky). Sweep 2 after one fixture fix: all 8 rounds clean at 75/75.

**Tests deleted:** none. Every failing test asserted rules verbatim-covered and uniquely derivable from PRD.md (`ERR_PLAN_TYPE_NOT_ALLOWED` §3.5, `ERR_CASH_INSUFFICIENT` §3.6, zero-weight allocation §3.7, special-assessment literals §3.9), so all were kept at full strength.

**Fixes applied to `test_helpers/`:** 1
- `/home/ubuntu/github/CodingPRD/tasks/task_1897_reserve_study_capital_reserve_funding/test_helpers/factories.py` — `create_state_rule_payload()`: now selects the canonical preset (`RULE_CA` / `RULE_NV` / `RULE_TX` from `constants.py`) matching the requested `state_code`, falling back to `RULE_CA` shape only for unknown codes. Previously it always built from `RULE_CA` content, so `seed_state_rule("NV")` and `seed_state_rule("TX")` silently produced CA-shaped rules (`min_percent_funded_pct: 50`, all three plan types allowed). The PRD-faithful implementation correctly rejected those setups (`ERR_PERCENT_FUNDED_BELOW_MINIMUM` at adoption for NV associations with tiny cash; THRESHOLD plans under TX adopting cleanly instead of hitting `ERR_PLAN_TYPE_NOT_ALLOWED`). One fixture bug masqueraded as all 5 failures — matching the triage hint.

**Fixes applied to `implementation/`:** none. The implementation was correct throughout; the sweep-1 failures were entirely the fixture's wrong statutory-rule seed data. The previously masked assertion paths (adoption plan-type gate, cash-insufficiency gate, state-beats-fiscal priority, zero-weight allocation branch, special-assessment literals `-597833` / `2028`) were verified passing in sweep 2.

## Step 8: Finalize PRD — 2026-08-15T01:12:00.000Z

Step 8 complete. `PRD_FINALIZED.md` exists at `/home/ubuntu/github/CodingPRD/tasks/task_1897_reserve_study_capital_reserve_funding/workspace/PRD_FINALIZED.md` as a byte-identical copy of `PRD.md` — the minimal correct patch is the identity.

## Summary

**Line counts / delta:** PRD.md = 295 lines, PRD_FINALIZED.md = 295 lines, 0% delta (`diff` confirms IDENTICAL).

**Changes:** none — zero edits were warranted.

**Why (per `<step_7_diff>` item):** The diff lists exactly one fix — the `test_helpers/factories.py` `create_state_rule_payload()` fixture bug — plus explicit statements that no `implementation/` fixes and no test deletions occurred, and that all five sweep-1 failing tests asserted rules "verbatim-covered and uniquely derivable from PRD.md". The fixture fix changed only which seed payloads tests POST to `/state-reserve-rules` (canonical `RULE_CA`/`RULE_NV`/`RULE_TX` presets from `test_helpers/constants.py`). The implementation holds no per-state rule content; it stores whatever `PlatformAdmin` seeds and enforces it at every gate — exactly PRD §3.1's "those rules are data rather than code … a configurable record consulted at every gate". This is the anticipated pure-fixture-bug case: no PRD silence, no PRD/impl mismatch, so no edit.

## Pre-edit search log (verification record for the no-edit decision)

For the single step_7 item I enumerated and read every impl path touching the five unmasked assertion subjects, and confirmed each is already uniquely pinned by existing PRD prose:

1. **Adoption plan-type gate** (`ERR_PLAN_TYPE_NOT_ALLOWED`, TX/THRESHOLD case)
   - Paths read: `implementation/routes/studies.py:241-269` (adopt flow, gate order: selected-plan count → plan-type → percent-funded), `implementation/routes/state_rules.py:29-83` (rule storage/validation), `implementation/services/calculations.py:7-12` (`find_state_rule`).
   - PRD §3.5 ("the selected plan's `plan_type` must appear in the state rule's `allowed_plan_types`") and §2.8 step 9 pin it verbatim. No wording gap; no edit.

2. **Percent-funded minimum gate** (`ERR_PERCENT_FUNDED_BELOW_MINIMUM`, NV tiny-cash case)
   - Paths read: `studies.py:268-269`; `calculations.py:66-72` (`compute_percent_funded`, 100.00 pin at FFB 0), `calculations.py:15-28` (`reevaluate_compliance`, same `>=` minimum comparison — an off-site path touching the same rule field, confirmed consistent).
   - PRD §3.5 "meet or exceed" and §2.10 pin it. The impl's `if state_rule` guard at `studies.py:264/268` is unreachable dead defense (association creation requires the rule per `ERR_STATE_RULE_MISSING`, rules are never deleted) — no observable behavior, nothing to pin. No edit.

3. **Cash-insufficiency gate** (`ERR_CASH_INSUFFICIENT`)
   - Paths read: `implementation/routes/expenditures.py:171-224` (approval cascade: state check :178 → component re-verify :186-187 → cash :190-191 → debit/recompute).
   - PRD §3.6 ("first re-verifies … and only then checks that the association's `reserve_cash_balance_cents` covers the `amount_cents`") pins both the gate and its position. No edit.

4. **State-beats-fiscal priority** (`test_approve_rejected_expenditure_state_beats_fiscal`)
   - Paths read: `expenditures.py:178-191` (state check precedes fiscal check); cross-checked the full ordering against PRD §2.8's cascade (step 5 target-state before step 11 fiscal sufficiency).
   - PRD §2.8 + §3.6 pin the order verbatim. No edit.

5. **Zero-weight allocation branch** (§3.7)
   - Paths read: `calculations.py:247-318` (`compute_allocation_lines` — weights, floor-then-largest-remainder with earliest-`created_at` tiebreak, and the S==0 branch assigning the entire contribution to the greatest-`current_replacement_cost_cents` component with strict `>` preserving earliest creation on ties); `get_active_included_components` at :41-50 (ACTIVE + included, `created_at` ASC).
   - PRD §3.7 pins both branches sentence-for-sentence, including both tiebreaks. No edit.

6. **Special-assessment literals** (`-597833` / `2028`, §3.9)
   - Paths read: `calculations.py:321-358` (`special_assessment_analysis`: association's `current_annual_contribution_cents`, live cash start, same year-step recursion with single half-up rounding per step, strictly-negative shortfall, `fiscal_year + (y+1)` offset, min balance, negated trough) and `compute_replacement_schedule` :82-104.
   - PRD §3.9 uniquely determines every figure the test asserts. No edit.

**Bottom line for Step 9:** PRD_FINALIZED.md = PRD.md verbatim; a fresh implementer reading it alone is already fully determined against the current implementation at every site Step 7 exercised, and no off-site path contradicts any existing sentence.

## Step 9: Complete PRD — 2026-08-15T01:25:00.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1897_reserve_study_capital_reserve_funding/workspace/PRD_COMPLETED.md` as a minimal patch over the finalized PRD, after an exhaustive walk of all 14 implementation source files (app/db/errors/middleware/response, 9 route modules, 2 service modules).

**Source vs output:** PRD_FINALIZED.md 295 lines / 47,753 chars → PRD_COMPLETED.md 297 lines / 50,082 chars (+2 lines, +2,329 chars).

**Counts:** 12 ambiguity-pins, 5 mismatch-revisions (17 changes total).

**Changes:**

- §2.1 — revise — mismatch — PRD demanded a mandatory `X-User-ID` + `X-User-Role` pair; impl enforces only the role header and never reads `X-User-ID`, so prose now pins `X-User-ID` as optional and never required/recorded/compared — middleware.py:9-14
- §2.2 — insert — ambiguity — pinned that undefined paths and unsupported methods return `ERR_NOT_FOUND` (404) in the standard envelope, and unexpected server failures return `ERR_INTERNAL` (500) — app.py:37-54
- §2.3 — insert — ambiguity — pinned pagination leniency: non-integer `limit`/`offset` fall back to defaults, out-of-range values are clamped (never rejected) — routes/studies.py:54-66 (same helper in all list modules)
- §2.3 — insert — ambiguity — pinned `has_more` formula: true exactly when `offset` + `limit` < `total_count` — response.py:29
- §2.4 — insert — ambiguity — pinned that `created_at`/`updated_at` and the envelope's `api_request_timestamp` also read the logical clock, and offset-less `to_iso8601` is interpreted as UTC — db.py:30-51, response.py:11, clock.py:28-31
- §2.7 — insert — ambiguity — pinned `version` starts at 1 on creation — db.py:50
- §2.8 step 3 — revise — mismatch — PRD pinned existence strictly before all shape checks; impl runs missing-field/unknown-field screens *before* body-FK existence on collection-level creates, so the cascade text now pins that order — components.py:68-78, studies.py:76-92, site_visits.py:51-62, expenditures.py:71-90
- §2.8 step 4 — revise — mismatch — blanket "monetary amounts strictly positive" contradicted impl (balances may be 0); now pins `current_replacement_cost_cents`/`amount_cents` strictly positive while `reserve_cash_balance_cents`/`current_annual_contribution_cents` may be zero — associations.py:99-103
- §2.8 step 4 — revise — mismatch — unknown-field screen scope pinned to creation + component-update payloads only; transition actions ignore bodies (impl enforces nowhere else) — all transition handlers
- §2.8 step 4 — insert — ambiguity — added missing shape rules impl enforces: `fiscal_year` integer, `site_visit_interval_years` positive integer, `disclosure_deadline_days` non-negative integer, `visit_date`/`incurred_date` parseable dates — state_rules.py:61-64, studies.py:95-96, site_visits.py:65-68, expenditures.py:96-99
- §3.5 — insert — ambiguity — pinned that adoption sets association compliance to `COMPLIANT` without advancing the association's `version`, and the newly adopted study's own plans are untouched (selected plan stays `SELECTED`) — studies.py:287-307
- §3.5 — insert — ambiguity — rejection `reason` is accepted but not persisted or echoed — studies.py:322
- §3.6 — insert — ambiguity — approval re-verification surfaces `ERR_COMPONENT_NOT_CURRENT` also when the association has no adopted study at all (not just superseded/retired cases) — expenditures.py:185-187
- §3.6 — insert — ambiguity — variance-acceptance `reason` likewise accepted but not persisted or echoed — expenditures.py:316
- §3.8 — insert — ambiguity — annual update advances `version` of every `ACTIVE` component, including one already at zero remaining life whose value does not change — associations.py:156-158
- §3.9 — revise — ambiguity — "offset of the earliest shortfall year" pinned to the one-based year-end index (first year-end shortfall → `fiscal_year` + 1) — calculations.py:343-349
- §5 — insert — mismatch — added `ERR_INTERNAL` | 500 row so the catalogue truly enumerates every error id the API can return — app.py:52-54

All endpoints, state transitions, formulas (FFB, percent-funded, replacement schedule, contribution solve incl. THRESHOLD/FULL floors, chronological/forward variance, tolerance, allocation-line largest-remainder, special-assessment projection), error ids/statuses, filters, and ordering rules not listed above were verified to be already uniquely pinned by the PRD as written.
