# Worklog — task_2474_environmental_justice_screening_permit_review

## Step 1: Create task directory — 2026-09-02T21:43:40.229Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2474_environmental_justice_screening_permit_review/` and its `workspace/` subdirectory. Index 2474 was pre-assigned by the invoking pipeline (no scan of ./tasks/ performed, per instruction — concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-02T23:08:00.000Z

All three artifacts are in place, parse cleanly, and pass the skill's linter.

## task_2474 — Environmental Justice Screening & Permit Review

**`/home/ubuntu/github/CodingPRD/tasks/task_2474_environmental_justice_screening_permit_review/SCAFFOLD.yaml`** (§1.0–§1.7, no design keys)
- `domain_name: environmental-justice-permit-review`, `api_prefix: /ej`
- **14 entities**: ScreeningArea, BurdenIndicator, Facility, PermitApplication, ApplicabilityDetermination, CumulativeImpactAssessment, ParticipationPlan, Venue, PublicMeeting, PublicComment, PermitCondition, PermitDecision, CommunityComplaint, Inspection (ApplicabilityDetermination and PublicComment are `common_fields: false` / immutable)
- **9 state machines**, **3 OCC concurrency rules** (412 `ERR_STALE_AREA_VERSION` / `ERR_STALE_APPLICATION_VERSION`)
- **16 calculations**, 3 of them dual-variant: `ej_screen_score` (STATEWIDE/COUNTY basis), `cumulative_impact_index` (SCREENING vs REFINED dispersion decay), `program_evaluation` (window basis); plus `residual_impact_index` with tiered mitigation caps, `community_benefit_obligation` (tier keyed on base, not total), `mitigation_credit_aggregation` (round-per-condition then sum), `required_comment_days` (30 + designation/translation/impact adders, cap 120), `participation_adequacy` with ordered deficiency reporting
- **40 ordered validations** (p1–p40), **56 endpoints**, **57 errors**, **8 roles** (ApplicantRepresentative is `identity: entity_backed:Facility`)
- Logical clock via `POST /_clock/set_current_utc`, default `2026-08-01T00:00:00Z`

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — single key `scaffold_difficulty_design`; all **9 rule_ids × 2 instances = 18**, covering variant divergence, round-then-sum, tier-key traps, revision cycles, parallel state dimensions, cascade regressions, validation-priority inversions, boundary/empty-pool semantics, and ledger restoration on rescission/cancellation.

**`SCAFFOLD_CORNER_DESIGN.yaml`** — single key `scaffold_corner_design`; **58 instances** spanning all nine claim-extraction sections: **49 executable** + **9 `excluded_because` stubs** (each citing a real §1.8 instance). Breakdown: entities 8, state_machines 9, calculations 6, validations 13, endpoints 4, errors 7, rbac 2, cross_cutting_complexity_layers 7, consistency_model 2.

**Verification**: `scaffold_lint.py` → `VERDICT: clean lint` (56 endpoints, 14 entities, 18 §1.8 instances, 49 §1.9 instances, 692 calls scanned); no duplicate instance names across design files, every stub's cited difficulty instance resolves, no forbidden concurrency vocabulary, all `${...}` placeholders closed.

One cross-file fix was needed: linter check (f) (FK reverse-reachability) matches sub-resource GETs against a literal `{id}` path placeholder, so all path parameters were renamed from `{areaId}`/`{applicationId}`-style to `{id}` (128 occurrences in SCAFFOLD.yaml, 1 + 12 in the design files). Worth noting for the skill spec — the `{id}` convention is implicit in the linter but not stated in SKILL.md. The hard constraint held: no sibling task directory was listed, read, or searched.

## Step 3: Copy shared files — 2026-09-02T23:11:07.392Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T23:28:03.522Z

Verification complete. All three Hard Contracts pass.

## Output

`workspace/PRD.md` — **476 lines**

## Section list

- `# Environmental Justice Screening & Permit Review API — Product Requirements Document`
- **§1 Introduction** (3 paragraphs; scenario rewritten as prose, `/ej` mount and logical clock introduced)
- **§2 Global Specifications & System-Wide Principles** — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Versioning · 2.5 The Logical Clock · 2.6 Numeric Precision, Rounding and Pinned Evaluation Order · 2.7 Screening Data Provenance and Version Guards · 2.8 Cascade Discipline Across the Screening Hierarchy · 2.9 Path and Payload Resolution Order · 2.10 Rejection Precedence (full 40-rung ladder) · 2.11 Segregation of Duties in the Review Chain · 2.12 Emissions Ledgers and the Area Load Cap
- **§3 Business Logic & Workflows** — 3.1 Building the Screening Baseline · 3.2 Facilities, Filing, and the Applicability Screen · 3.3 Cumulative Impact Assessment and Independent QA · 3.4 Enhanced Public Participation · 3.5 Accessible Meeting Locations and Comment Intake · 3.6 Permit Conditions and Residual Impact Mitigation · 3.7 Issuance, Denial Authority and Rescission · 3.8 Community Complaints, Priority Scoring and Inspections · 3.9 Revision Cycles, Withdrawal and Program Evaluation
- **§4 Endpoint Definitions** (intro + 4-column table, 56 rows)
- **§5 Error Code Catalogue** (2-column table, 57 rows)

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 141 required, 141 present, 0 missing
- endpoints[].request_body: 76 unique (138 occurrences) required, 76 present, 0 missing
- endpoints[].query_params: covered within the 76 (limit, offset, status, indicator_code,
  facility_type, review_track, language, priority_tier, screening_area_id, facility_id,
  basis, period_start, period_end, designation), 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 40 checked, 40 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint +
  expected_screening_area_version / expected_application_version + error_id all named), 0 missing
- state_machines[].transitions: 53 checked, 53 fully expressed, 0 missing
- calculations[]: 16 checked, 16 fully expressed, 0 missing (all 46 named constants verified
  present verbatim in the prose)
- validations[] conditions: 57 error ids checked, 57 matchable to prose, 0 missing
- endpoints[].side_effects / applies_to: 56 endpoints checked, all side-effect bullets expressed, 0 missing
- entities[].fields[] structured content: 14 entities checked, 14 reconstructible from prose, 0 missing
- sibling-branch symmetry: 14 groups checked (screen STANDARD/ENHANCED, advance standard/enhanced,
  QA ACCEPT/RETURN, triage ACCEPT/DISMISS, resolve RESOLVED/REFERRED, decision ISSUE/DENY,
  finding VIOLATION_CONFIRMED/NO_VIOLATION, method SCREENING_LEVEL/REFINED, score
  STATEWIDE/COUNTY, basis DECISION_DATE/APPLICATION_DATE, 4 designation transitions,
  rescind by track, withdraw by track, half-open vs closed interval geometry),
  14 with equal prose density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 925
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Non-truncation and hygiene

- File ends at the final row of the §5 table (`ERR_REFERRAL_UNSUPPORTED | 422 Unprocessable Entity`) — a real section boundary, not mid-sentence. No audit footer in the file.
- §4 table: 56/56 endpoints present, each with the exact scaffold role set (programmatically diffed, 0 mismatches). §5 table: 57/57 errors with exact HTTP statuses (0 mismatches).
- §2.2 diffed byte-for-byte against `section-2.2-response-structure.md` — identical (only a trailing `---` separator added, as in the reference example PRD).
- No difficulty-instruction text: greps for "harder than expert", "difficulty", "expert level", "test_recipe", "scaffold" return nothing. No fuzzy hedging ("approximately"/"roughly"/"conservatively") and no concurrency framed as simultaneity — the one "simultaneous" hit is the venue attribute "simultaneous interpretation".
- The two withheld design files were never opened, grepped, or referenced.

Two small repairs were made during verification: currency tier thresholds rewritten as `500000.00`/`100000.00` (I had comma-grouped them), and the two `data_status` transitions restated as explicit `CURRENT → STALE` / `STALE → CURRENT` arrows.

**Orchestrator's independent truncation check** (per pipeline instruction): `tail -12 PRD.md` ends cleanly at the last `ERR_REFERRAL_UNSUPPORTED` table row; section headings walk 1 → 5 with no gaps; 56 endpoint rows and 57 error rows confirmed by grep; no difficulty-instruction leak. PRD accepted without regeneration.

## Step 5: Generate unit tests — 2026-09-03T02:35:00.000Z

The suite is complete. Final state:

**Files written**

`test_helpers/` — 9 modules (`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`), ~3.4k lines: PRD §5 error/status map registration, one client method per endpoint, payload factories, money/ratio assertion helpers, and 30+ named scenario builders/pytest fixtures (AREA_A–AREA_M chains, `venue_pair`, complaint pools).

`test_suite/` — `conftest.py` + 16 test modules, **91 tests**, all collected cleanly (`pytest --collect-only` → 91, pyflakes clean apart from the intentional fixture re-exports in `conftest.py`).

New in this pass: `test_14_participation_capacity_and_venue_slots.py` (8), `test_15_compensating_reversals.py` (4), `test_16_inspection_assignment_eligibility.py` (2).

**Coverage against the two design indices (verified programmatically)**

- Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`): 49 active instances → **49 tests**, exactly one per instance, no bogus tags, none of the 9 `excluded_because:` stubs emitted.
- Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 18 instances (9 rule_ids × 2, no stubs) → **42 tests**, every instance at ≥2 tests.
- Every test docstring ends in exactly one `Design:` line; every quoted PRD sentence survives a whitespace-normalized literal grep of `workspace/PRD.md`; no file contains the forbidden design-document references.

**Skipped instances**: none on the PRD-first filter — all 18 depth and all 49 active breadth instances had verbatim, uniquely-deriving PRD coverage. The only untranslated entries are the 9 pre-marked queue-B stubs (`application_revision_cycle_reenters_enhanced_review`, `screening_area_two_state_dimensions_move_independently`, `mitigation_credit_rounds_per_condition_before_summing`, `community_benefit_surcharge_tier_read_from_base`, `decision_state_check_outranks_assessment_check`, `designation_cascade_flips_standard_track_to_enhanced`, `ej_screen_score_two_percentile_bases_diverge`, `area_permitted_load_ledger_reconciles_after_reversal`, `rescission_saga_reverses_every_issuance_side_effect`), each of which duplicates a queue-A instance that is covered.

**Notable arithmetic pinned in the new files**: advance-to-decision refused with `ERR_ASSESSMENT_NOT_ACCEPTED` on a `CLOSED`/`COMPLIANT` plan whose `required_comment_days` stays 60 (never 70) because the accept-time recompute skips `CLOSED` plans; venue slots half-open with a 60-minute candidate-only buffer (21:00 start collides, 21:30 start touches at 20:30 and is accepted); area engagement windows closed intervals (2026-10-14 collides, 2026-10-15 opens to 2026-12-28 at 75 days); rescission decrements both ledgers 50.00 → 0.00 while retaining 5225.00/100225.00 and reopening the plan to 2026-10-25 with 15 granted days; cancellation returns `booked_meeting_count`/`meeting_count` to 1 and frees the buffered interval; empty narrowed pool → `ERR_NO_ELIGIBLE_COMPLAINT` with the unnarrowed call scoring the neighbour at 15.00/`TIER_3`.

Nothing under `workspace/implementation/` was read or written, and no sibling task directory was touched.

## Step 6: Generate implementation — 2026-09-03T00:30:00.000Z

Implementation complete and verified.

## Files written
All under `workspace/implementation/`:

- `start.sh` (executable), `requirements.txt` (`Flask>=3.0.0`)
- `app.py` — app factory, `ApiJSONProvider` (Decimal → JSON number, insertion-order keys), `ApiError`/`HTTPException`/catch-all handlers
- `constants.py` — roles, role read-sets, all enums, every calculation constant as `Decimal`/`int`
- `errors.py` — all 57 error ids → HTTP status, `ApiError`, `bad_request`
- `db.py` — in-memory `Store` (14 dicts), logical UTC clock seeded at `2026-08-01T00:00:00Z`, `new_row`/`touch` (request-scoped version-bump dedup), `ordered`, ISO-8601 formatting with exactly 3 fractional digits
- `response.py` — envelope builders (`meta.api_request_id` = `req_` + 20 uppercase alnum, `api_request_timestamp` = real wall clock), `paginate`
- `middleware.py` — `X-User-ID` / `X-User-Role` auth per the rejection ladder
- `validators.py` — typed field/query extractors (bools rejected for numerics, explicit `null` = absent for optionals)
- `serialize.py` — 14 entity serializers; internal keys (`_seq`, `_starts_at`, `_ends_at`) never emitted
- `services/calc.py`, `services/repo.py`, `services/cascade.py` — 9 calculations, lookups/selections, and all derived-field/counter/ledger cascades
- `routes/{reference,applications,assessments,participation,conditions,complaints}.py` — 6 blueprints
- `routes/__init__.py`, `services/__init__.py` (empty)

## Endpoint coverage
Programmatic diff of the registered URL map against `SCAFFOLD.yaml` (path params normalized): **declared 56, implemented 56, missing none, extra none** — including `POST /_clock/set_current_utc` outside the `/ej` prefix.

## start.sh
Honors `$PORT` (`app.py` reads `os.environ["PORT"]`, default 10000), binds `0.0.0.0`, and runs in the foreground via `exec python3 app.py` (no `&`, no reloader, `threaded=False`). The `pip install` is guarded by an `import flask` probe so the per-test reboots don't contend on pip.

## Storage / seeding
Verified by grep: no `sqlite3`, `open(`, `json.dump`, `pickle`, `shelve`, or `/tmp` anywhere in the tree. All state is process-local dicts keyed by UUID. A fresh boot returns `total_count: 0` for every collection — nothing is seeded. Note the collection-level `GET /ej/screening-areas`, `/ej/facilities`, `/ej/venues` correctly return 405 because SCAFFOLD declares those lists only as nested routes.

## Smoke test (fresh boot, all green)
Full happy path exercised end to end: clock set → area → 3 burden indicators with OCC `expected_screening_area_version` → facility → application → submit → screen → assessment → submit-qa → QA accept → plan patch/open → venue → meeting → comment → clock advance → plan close → condition with OCC `expected_application_version` → advance-to-decision → ISSUE → program-evaluation → complaint → triage → assign-next → complete with `VIOLATION_CONFIRMED` → rescind → recertify.

Derived values propagated correctly: area scores 84.65 statewide / 51.83 county → `SEVERELY_OVERBURDENED` with `translation_required: true`; screening produced all four trigger codes and the ENHANCED track; `pre_mitigation_index` 74.26 − credit 30.0 → `residual_impact_index` 18.57; ISSUE moved `permitted_load_tpy` to 10.0; a confirmed violation added 5 enforcement points, flipped `data_status` to `STALE`, and rescored the area to 87.15. Version counters advanced monotonically with one bump per row per request.

Cleanup: `__pycache__` dirs removed, no lingering server processes.

## Step 7: Run tests and iterate — 2026-09-03T01:28:40.141Z

Clean 8-round sweep: **91/91 passed in all 8 parallel rounds.**

## Summary

**Iterations run:** 2 (iteration 1: 84/91 in all 8 rounds, 7 deterministic failures; iteration 2: 91/91 in all 8 rounds).

Failures were fully deterministic (identical in all 8 rounds) — no flakiness or load-induced noise. No implementation changes were needed; every defect was in the test artifact.

**Tests deleted:** none.

**Assertions removed under STEP 1c (partial coverage / unique-derivability split)** — `test_suite/test_10_mitigation_credit_and_residual_impact.py`:
- `test_the_credit_total_sums_the_rounded_values_not_the_raw_products` and `test_the_one_cent_credit_difference_shows_up_in_the_approved_net`: dropped the `approved_net_emissions_tpy == 76.28` assertions (COMPUTED-FIELD / write-timing silence). PRD §3.6 gives the formula ("From the credit total comes the application's `approved_net_emissions_tpy` figure…") but its recomputation sentence enumerates exactly two recomputed figures — "recomputes the credit aggregation and the residual index" — omitting approved net; §3.2 initialises it at 0.00 and §3.7 is the only place that says it "is set to". Decisive evidence of non-unique derivability: the passing test `test_11…test_an_unmitigated_residual_answers_before_the_benefit_shortfall` asserts `approved_net_emissions_tpy == 0.00` on a `PENDING_DECISION` application with 80.00 proposed / 0.00 credit — under the live-derivation reading that value would be 80.00. The two tests were mutually unsatisfiable. Kept both tests' covered assertions (`total_mitigation_credit_tpy == 3.72`, `residual_impact_index == 78.02`, the anti-3.71 guard).
- Scaffold rule driving both: `Difficulty/combinatorial_formula/mitigation_credit_round_per_condition_then_sum`.

**Assertion relaxed (coverage correction)** — `test_suite/test_12_application_revision_cycle.py`:
- `test_the_voided_assessment_shortens_the_required_comment_period` and `test_the_rescreen_returns_the_file_to_enhanced_review_with_a_new_row`: the two `POST …/screen` calls used `validate_success` (200-only) while `test_03`'s `test_screen_response_exposes_its_own_cascade_immediately` uses `assert_created` (201) on the same endpoint. PRD §4 supports both readings — the screen mints an ApplicabilityDetermination, yet the 201 enumeration does not name it and "every state transition" gets 200. Switched to `get_success_data` (any 2xx, envelope still validated). Scaffold rule: `Difficulty/non_linear_state_machine/application_revision_cycle_enhanced_returned_resubmit`.

**Fixes applied to `test_suite/` (STEP 2 — test bug, request identity / call convention):**
- `test_01_authentication_and_role_enforcement.py`, `test_applicant_representative_cannot_run_the_screen`: the trailing `assert_empty_listing` read `GET …/applicability-determinations` with `INSPECTOR_2_HEADERS`. PRD §4 does not authorise `Inspector` on that listing, so the PRD-faithful implementation correctly returned `ERR_ROLE_NOT_PERMITTED`. Switched to `ANALYST_HEADERS` (an authorised role) and added the import.
- `test_03_application_lifecycle_and_version_guards.py`, `test_withdrawn_application_is_terminal_and_rejects_resubmit`: called `api.withdraw_application(id, payload, headers)` and `api.resubmit_application(id, payload, headers)`, but those `ApiClient` methods are declared `(id, headers, payload=None)` — the payload dict was being sent *as the headers*, so the request carried no `X-User-ID`/`X-User-Role` and correctly got `ERR_MISSING_AUTH_HEADERS`. Fixed to pass `payload=` as a keyword.
- `test_07_decisions_and_program_evaluation.py`, `test_withdraw_cancels_the_plan_the_meeting_and_the_condition`: same `withdraw_application` argument-order bug; same fix.

**Fixes applied to `test_helpers/`:** none — the client signatures were self-consistent (optional bodies follow `headers`); only the three call sites in `test_suite/` violated the convention, so fixing them was the local, minimal correction.

**Fixes applied to `implementation/`:** none. All 7 failures traced to the test layer.

**Orchestrator's independent artifact verification** (per standing caution that a Step 7 subagent can claim a clean sweep with no artifacts behind it): all 8 `workspace/implementation/results.{1..8}.json` exist, each parses to `passed=91 / total=91 / failed=0`; `workspace/sweep.log` ends with `Results: 91/91 passed, 0 failed, 0 errors, 0 skipped`; results mtime 01:15:56 postdates the last test-file edit at 01:10:45, so the green sweep genuinely ran after the fixes. `test_suite/` still holds 91 test functions (no silent deletions). Sweep artifacts accepted.

**Step 8 skip decision:** NOT skipped. Step 7 ran 2 iterations with `test_suite/` fixes and two STEP-1c assertion removals, so the PRD left at least those behaviours under-determined even though `implementation/` needed no fix.

## Step 8: Finalize PRD — 2026-09-03T01:39:40.988Z

Done. `PRD_FINALIZED.md` written with two inline edits.

## Line counts
- `PRD.md`: 476 lines; `PRD_FINALIZED.md`: 476 lines — **0.0% line delta** (both edits are inline within existing paragraphs; 2 lines revised, ~+130 words ≈ +0.9% by character count).

## Changes
- **§3.6 (Permit Conditions and Residual Impact Mitigation)** — *revise* — pinned the write timing of `approved_net_emissions_tpy`: the formula is derived at decision time, the stored application field stays `0.00` from filing until an issuance sets it and returns to `0.00` on rescission, and credit-aggregation recomputation (condition attach, condition void, withdrawal, any other cascade) rewrites only `total_mitigation_credit_tpy` and `residual_impact_index` — `implementation/services/cascade.py:150-158`, `implementation/routes/conditions.py:154`, `implementation/routes/applications.py:66`.
- **§4 (Endpoint Definitions preamble)** — *revise* — added `POST /ej/permit-applications/{id}/screen` to the `201 Created` set and pinned that its `data` carries the minted `ApplicabilityDetermination`, not the routed application; qualified the 200-OK sentence to "every **other** state transition" — `implementation/routes/applications.py:167`.

## Per-edit pre-edit search log

**Edit 1 — subject: the `approved_net_emissions_tpy` quantity (application field, decision field, and its derivation).**
- (b) Paths enumerated (`grep -rn "approved_net" --include=*.py`, plus full reads of `routes/conditions.py`, `routes/applications.py`, `services/calc.py`, `services/cascade.py`, and the program-evaluation handler): `routes/applications.py:66` (initialised `0.00` at filing); `services/calc.py:124` `approved_net_emissions()`; `services/cascade.py:150` `recompute_credit()` (writes `total_mitigation_credit_tpy` + `recompute_residual` only — never approved net); `routes/conditions.py:63` (condition attach), `:95` (condition void), `routes/applications.py:268` (withdrawal cascade), `routes/applications.py:185`/`:205`/`:239` and `cascade.stale_data_cascade` (index recomputes that do not touch approved net); `routes/conditions.py:131` (computed locally at decision time, feeding `minimum_benefit_required` at `:146` and the load cap at `:148`); `:154` (issuance sets the application field); `:172`/`:204` (decision-row value on ISSUE/DENY); `:247` (rescission zeroes it); `serialize.py:108`/`:256`; `routes/complaints.py:301-341` program evaluation (confirmed it never reads approved net).
- (c) Adjustment: originally drafted as "evaluated at decision time"; softened/re-scoped to "derived when a decision is taken … until an **issuance** sets it" so the DENY path (which computes the value but writes `0.00` to the decision and leaves the application untouched) and the rescission path are not mis-described. Explicitly enumerated the cascade callers (attach/void/withdraw/"any other cascade") so the withdrawal and stale-data recomputes stay covered without asserting a closed list.

**Edit 2 — subject: HTTP status codes and `data` payloads across every endpoint.**
- (b) Paths enumerated (`grep -rn "object_response\|list_response\|return \"\", 204" routes/*.py`, all 60 return sites): 201 returns at `applications.py:70` (application), `:167` (screen → determination), `reference.py:65`/`:178`/`:206`/`:243` (area, indicator, facility, venue), `assessments.py:98`, `conditions.py:66` (condition), `:178`/`:210` (decision issue/deny), `participation.py:200` (meeting), `:280` (comment), `complaints.py:61` (complaint), `:230` (assign-next inspection); `204` at `conditions.py:98` (condition void); every other mutation/read at `200` including `reference.py:277` (`/_clock/set_current_utc` → `{"current_utc": …}`) and `assessments.py:127/149/171/211`, `participation.py:35-141/237`, `complaints.py:117/137/163/268`, `conditions.py:265`, `applications.py:78/137/189/208/242/273`.
- (c) Adjustment: changed "every state transition" to "every **other** state transition" rather than deleting the clause, so all remaining transitions (submit, advance, return, resubmit, withdraw, QA, plan open/extend/close, meeting cancel, triage/reopen/resolve, inspection complete, rescind) keep their pinned `200`; scoped the payload claim to the screen alone so §2.2's general "created or updated resource" rule stays true elsewhere.

**Not patched (verified PRD already determines, or pure fixture bug):** the `applicability-determinations` listing excluding `Inspector` (PRD §4 table row already matches `constants.READ_NO_INSPECTOR_NO_PUBLIC`), and the two `withdraw_application`/`resubmit_application` argument-order defects in `test_suite/` (client-call-convention bugs with no PRD surface).

**Orchestrator's verification:** whitespace-normalised diff of `PRD.md` vs `PRD_FINALIZED.md` shows exactly two changed lines (301 and 355), both inline within existing paragraphs — no new sections, no dropped content; file still 476 lines and ends at the final §5 error row.

## Step 9: Complete PRD — 2026-09-03T02:00:20.768Z

`PRD_COMPLETED.md` is written.

## Source vs output
- `PRD_FINALIZED.md`: 476 lines, 98,429 chars
- `PRD_COMPLETED.md`: 476 lines, 104,945 chars (**+6,516 chars**, 31 lines revised in place, no sections added, document still ends at the §5 error catalogue table)

## Counts
- ambiguity-pins: **22**
- mismatch-revisions: **9**

## Changes
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from host real time, not the logical clock — `response.py:19`
- §2.2 — insert — ambiguity — pagination `meta` keys only on list envelopes; `total_count` is pre-window filtered size; `has_more` formula pinned — `response.py:28-34`
- §2.3 — insert — ambiguity — `created_at` ties stabilised by insertion order; determination list's third sort key is reverse insertion order — `db.py:141`, `applications.py:119`
- §2.4 — insert — ambiguity — one `version` bump per row per request; a row created then rewritten in-request returns at `version` 1 — `db.py:100-135`
- §2.5 — insert — ambiguity — clock endpoint returns 200 with a single `current_utc` at three fractional digits; input normalised to UTC — `reference.py:275-277`
- §2.5 — revise — mismatch — `starts_at`/`ends_at` compared as exact instants, not at minute precision; echoed in client spelling — `cascade.py:262,320`, `participation.py:183-185`
- §2.6 — insert — ambiguity — decimals serialised as bare JSON numbers so trailing zeros vanish in the text — `app.py:29`, `serialize.py:12`
- §2.7 — insert — ambiguity — `*_version_after` stamps refresh only when the request also advances the parent's `version` — `assessments.py:148,169`
- §2.9 — insert — ambiguity — assign-next resolves its optional `screening_area_id` → `ERR_SCREENING_AREA_NOT_FOUND` — `complaints.py:186-188`
- §3.1 — insert — ambiguity — tier-skipping and no-change designation re-evaluations: escalate/recompute iff the new value differs and is not `UNDESIGNATED` — `cascade.py:54-58`
- §3.1 — revise — mismatch — area complaints rescored unconditionally, not only when the county score moves — `cascade.py:57,88-91`
- §3.1 — revise — mismatch — recertification carries the full designation cascade plus `active_indicator_count` and complaint rescoring — `reference.py:82-83`
- §3.2 — insert — ambiguity — `prior_application_id` only has to resolve; no facility/status constraint — `applications.py:45-46`
- §3.2 — insert — ambiguity — auto-escalation recomputes an existing non-cancelled plan instead of creating one — `cascade.py:72-76`
- §3.3 — insert — ambiguity — no application-state gate on authoring or revising an assessment — `assessments.py:53-57`
- §3.3 — insert — ambiguity — submit-for-QA checks assessment state before application state — `assessments.py:120-124`
- §3.3 — revise — mismatch — revision keeps stored values for omitted inputs and leaves the application's indices, `version` and stamp untouched — `assessments.py:187-211`
- §3.3 — insert — ambiguity — governing-assessment final tie by reverse insertion order — `cascade.py:123`
- §3.4 — revise — mismatch — `required_comment_days` is **not** recomputed on extension; recomputed on screen-with-existing-plan and only on designation changes away from `UNDESIGNATED` — `participation.py:108-121`, `cascade.py:54`
- §3.4 — insert — ambiguity — plan PATCH fields individually optional; omitted fields left as stored — `participation.py:62-65`
- §3.4 — insert — ambiguity — `additional_days` is a whole number ≥ 1 — `participation.py:101`
- §3.5 — insert — ambiguity — the comment-window test is the only plan gate on booking: window-less plans always fail, `CLOSED` plans with a window do not — `participation.py:161-170`
- §3.5 — insert — ambiguity — `starts_at`/`ends_at` echoed verbatim — `participation.py:183-185`
- §3.6 — revise — mismatch — residual recompute list corrected: not on QA `RETURN` and not on assessment revision — `assessments.py:146-149,202-211`
- §3.7 — insert — ambiguity — omitted `community_benefit_base_usd` computes as 0.00 while the stored field stays null — `conditions.py:144,169`
- §3.7 — insert — ambiguity — a `DENY` with no `denial_basis` yields `ERR_DENIAL_BASIS_UNSUPPORTED`, not `ERR_INVALID_REQUEST` — `conditions.py:181-189`
- §3.8 — insert — ambiguity — complaint list id filters matched literally, unknown id yields an empty page — `complaints.py:81-84`
- §3.8 — insert — ambiguity — missing `dismissal_reason` is `ERR_INVALID_REQUEST` — `complaints.py:100-101`
- §3.8 — insert — ambiguity — "narrows to a single complaint" = area supplied and area holds exactly one complaint of any status; runs before day-capacity — `complaints.py:190-193`
- §3.8 — insert — ambiguity — "latest `COMPLETED` inspection" = most recently created — `complaints.py:152-155`
- §3.9 — revise — mismatch — withdrawal also voids `INVALIDATED` assessments; `open_plan_count` decremented by 1 only from `OPEN`/`EXTENDED`; `approved_net_emissions_tpy` untouched — `applications.py:258`, `cascade.py:244`
- §3.9 — revise — mismatch — program evaluation returns **eight** figures (not seven) and is a plain object with no audit fields — `complaints.py:371-383`
- §3.9 — insert — ambiguity — `mean_comment_days` reads the non-cancelled plan; a plan-less enhanced application contributes 0 but still counts in the divisor — `complaints.py:358-369`

Notable finding: §3.4's claim that `required_comment_days` is recomputed "when an extension is granted" and §3.6's "recomputed after any change to the governing assessment" were both flatly wrong against the implementation — extension and assessment revision leave those figures alone — so both were revised rather than merely annotated.

**Orchestrator's verification:** `PRD_COMPLETED.md` is 476 lines with 29 headings, 56 endpoint rows and 57 error rows intact; `diff PRD_FINALIZED.md PRD_COMPLETED.md` shows 31 changed lines, all in-paragraph; the document ends at the final `ERR_REFERRAL_UNSUPPORTED` row — no truncation.

---

## Pipeline complete — 2026-09-03T02:00:20.768Z

All nine steps ran to completion. Final state: 3 scaffold artifacts, `PRD.md` → `PRD_FINALIZED.md` → `PRD_COMPLETED.md`, `test_helpers/` (9 modules) + `test_suite/` (conftest + 16 modules, 91 tests), `workspace/implementation/` (56/56 endpoints), and `results.{1..8}.json` all green at 91/91.
