# Worklog — task_2557_state_veterans_home_admission_per_diem

## Step 1: Create task directory — 2026-09-03T09:41:21.385Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2557_state_veterans_home_admission_per_diem` and its `workspace/` subdirectory. Output directory was pre-assigned by the invoking pipeline (index 2557 fixed by scenario number); no index scan/allocation performed, per instructions.
## Steps 2-4: Generate the three scaffold artifacts — 2026-09-03T11:50:00Z

Generated purely from the verbatim scenario plus `skills/prd-bench-scaffold-generator/SKILL.md`; no sibling
`tasks/task_*/` directory was listed, globbed, grepped or read at any point.

- `SCAFFOLD.yaml` (§1.0–§1.7, 2624 lines): 12 entities, 8 state machines, 3 concurrency rules,
  11 calculations, 38 validations, 48 endpoints, 47 errors, 7 roles. `api_prefix: /svh`,
  `consistency_model: immediate`, primary archetype quota_allocation / secondary ledger_reconciliation.
  Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 2353 lines): single top-level key, 9 rules / 23 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 5949 lines): single top-level key, 9 sections / 93 instances
  (69 full test recipes + 24 `excluded_because` stubs, every cited §1.8 instance resolved).
  All 47 §1.6 error ids appear somewhere in the corner design.

Two SCAFFOLD.yaml consistency fixes made while writing §1.9:
1. `POST /svh/_ops/census-run` PNA / cost-share postings pinned to once per resident per calendar month
   (re-running the checkpoint for the same month never double-credits or double-debits).
2. `POST /svh/residents/{id}/discharge` side effects aligned with the CarePlan state machine:
   DRAFT plans -> VOID, ACTIVE/REVIEW_DUE plans -> SUPERSEDED.

`python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2557_state_veterans_home_admission_per_diem`
-> 48 endpoints, 12 entities, 23 §1.8 instances, 69 §1.9 instances, 1263 calls scanned,
`VERDICT: clean lint`.

## Step 2: Generate scaffold (subagent) — 2026-09-03T11:49:39.442Z

(Orchestrator record. Note: the Step 2 subagent wrote its own entry above under the heading
"Steps 2-4"; that heading is a mislabel by the subagent — it covers Step 2 only. Left in place,
append-only.)

Verbatim subagent summary:

Scaffold generation for `task_2557_state_veterans_home_admission_per_diem` is complete and lint-clean.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2557_state_veterans_home_admission_per_diem/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2557_state_veterans_home_admission_per_diem/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2557_state_veterans_home_admission_per_diem/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    48
  §1.1 entities declared:     12
  §1.8 instances scanned:     23
  §1.9 instances scanned:     69
  Calls scanned (§1.8+§1.9):  1263

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Outputs

All under `/home/ubuntu/github/CodingPRD/tasks/task_2557_state_veterans_home_admission_per_diem/`:

- `SCAFFOLD.yaml` — 2624 lines, 166 KB. Top-level keys only: scenario, domain_name, api_prefix (`/svh`), complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles. Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` (verified by load).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2353 lines, single top-level key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5949 lines, single top-level key `scaffold_corner_design`.
- `worklog.md` — appended with the generation record.

All three tails end at real structural boundaries (a `shared_operations:` list, a closing assert line, and a stub `rationale:` line respectively).

## Counts

- §1.1–§1.7: 12 entities, 8 state machines, 3 concurrency rules (OCC on CareUnit / Resident / PerDiemClaim), 11 calculations, 38 validations, 48 endpoints, 47 errors, 7 roles.
- §1.8: 9 rules / 23 instances (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 3).
- §1.9: 9 sections / 93 instances — entities 14, state_machines 16, calculations 15, validations 17, endpoints 9, errors 8, rbac 5, cross_cutting_layers 7, consistency_model 2. That is 69 full test recipes plus 24 `excluded_because` stubs; every stub's cited §1.8 instance resolves, and all 47 §1.6 error ids are referenced somewhere in the corner design.

## Two SCAFFOLD.yaml consistency fixes found while writing §1.9

1. `POST /svh/_ops/census-run` — PNA credit and cost-share debit postings were unguarded, so re-running the checkpoint for the same month would double-post. Both are now pinned to once per resident per calendar month, with explicit rules for which counters a skipped resident does and does not appear in.
2. `POST /svh/residents/{id}/discharge` — the endpoint's side effects said all ACTIVE/REVIEW_DUE care plans go to VOID while the CarePlan state machine said DRAFT → VOID and ACTIVE/REVIEW_DUE → SUPERSEDED. Aligned the endpoint to the state machine (which §1.8 and §1.9 asserts already relied on).

The hard constraint was honored throughout: no sibling task directory was listed, globbed, grepped, or read.

## Step 3: Copy shared files — 2026-09-03T11:49:39.442Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-09-03T12:09:00.000Z

Truncation guard verified by orchestrator: `workspace/PRD.md` is 488 lines, headings `## 1. Introduction`,
`## 2. Global Specifications & System-Wide Principles`, `## 3. Business Logic & Workflows`,
`## 4. Endpoint Definitions`, `## 5. Error Code Catalogue`; the file ends on the final row of the §5
error table (`| ERR_PNA_RESERVE_BREACH | 409 |`) — a real section boundary, not mid-sentence.
No difficulty/meta-text ("expert level", "harder than") and no "SCAFFOLD" reference leaked into PRD.md.

Verbatim subagent summary:

PRD generation is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2557_state_veterans_home_admission_per_diem/workspace/PRD.md` — **488 lines**, ending cleanly on the last row of the §5 error table (`| \`ERR_PNA_RESERVE_BREACH\` | 409 |`) with no audit footer.

**Structure**
- `## 1. Introduction` (3 paragraphs, pain-point framing)
- `## 2. Global Specifications & System-Wide Principles` — 11 domain-derived subsections (actors/RBAC; the fixed §2.2 envelope; pagination/filtering/ordering; common record properties & version semantics; the logical clock; version pinning on contested writes; path & FK resolution order; cascade discipline; beds/rates/cents/rounding; segregation of duties; the 16-rung validation ladder)
- `## 3. Business Logic & Workflows` — 9 subsections (homes & bed capacity + recognition; intake/eligibility/redetermination; waitlist priority & offers; assessment & admission decision; care planning & transfers; bed-holds/readmission/discharge; income, cost share & trust fund; survey/certification/recognition cascades; census materialisation + per diem claims & adjudication)
- `## 4. Endpoint Definitions` — 4-column table, **48 rows** (21 GET, 27 POST)
- `## 5. Error Code Catalogue` — 2-column table, **47 rows**

**Contract reports (verification run mechanically, not in the file)**
- **Contract 1 — Field-Name Coverage: PASS.** 164 required identifiers extracted from `entities[].fields[].name` + common fields + every endpoint `input`/output-object key. After stripping fenced blocks and extracting inline-code tokens, 0 missing; all 164 appear as standalone backticked tokens. (First pass used a looser regex that was corrupted by the ```json fences in §2.2; the corrected fence-stripped pass is the authoritative one.)
- **Contract 2 — Rule Coverage: PASS.** All 47 error IDs appear in §1–§3 prose (not merely in the §5 table); all 40 validation rungs are represented in the §2.11 ladder plus their guarded workflows; all 3 `concurrency_rules` with their `expected_*` fields and 412 codes are in §2.6; all 11 calculations are expressed in prose with every numeric constant present (verified programmatically — 0 missing, `BEHAVIORAL_RISK_POINTS` -30 appears as "a deduction of thirty points"); all 40 state-machine transitions across 8 machines are covered, including the 4-hop decertification / 3-hop reinstatement cascades, the 4-hop admission cascade, `CarePlan DRAFT -> VOID` on discharge, and the `WaitlistEntry` cancel branches; every `applies_to` scope, both dual-variant calculations (`resident_cost_share_monthly`, `per_diem_claim_amount`) with their sibling-branch symmetry, and all 8 ops-checkpoint counters with their "counted in neither" pins are present. An enum/constant sweep of every UPPER_SNAKE token in the scaffold found no missing enum value.
- **Contract 3 — §3 Path Purity: PASS.** 1,259 backticked tokens in §3; 0 start with `/`, 0 are bare HTTP methods, 0 are method+path combos; 0 raw occurrences of `/svh` anywhere in §3. Endpoints are referenced by state-transition framing and role+action verb.

**Other guards:** §2.2 is byte-identical to `section-2.2-response-structure.md` (substring match confirmed). No difficulty/meta-text leaked ("expert level" / "harder than" both absent). Only 2 fenced blocks exist (the §2.2 JSON envelopes) — no pseudocode, no `round_half_up(...)`-style formula text. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Scaffold inconsistencies I resolved (decisions applied consistently throughout):**
1. Applicant creation — endpoint side effect says `priority_score` null, entity default says 0: chose `priority_class` null, `priority_score` 0.
2. Recognition action — state machine says `recognition_effective_date` = clock date, endpoint says supplied `effective_date`: chose the endpoint's `effective_date`.
3. Trust-fund reversal has no `effective_date` input but the calculation references "the request's effective_date": specified that the `REVERSAL` copies the reversed row's `effective_date`.
4. Survey-result cascade — endpoint says DRAFT claims "for the unit" are voided, state machine hop 4 says "of that home": wrote it as every DRAFT claim of the home (which necessarily includes the unit's).
5. Three unassigned error cases were given the nearest catalogued code: assessment submit with the applicant outside `{ELIGIBLE, WAITLISTED}` -> `ERR_APPLICANT_STATE_INVALID`; determination on an `INELIGIBLE` applicant with no `amended_*` field -> `ERR_APPLICANT_STATE_INVALID`; discharge from `ADMITTED` citing `BED_HOLD_EXPIRED` -> `ERR_RESIDENT_STATE_INVALID`.

## Step 5: Generate unit tests (subagent) — 2026-09-03T13:04:00.000Z

Verbatim subagent summary:

All work is complete. Final report:

## Files written

**`test_helpers/` — 9 files, 2,045 lines** (infrastructure, unchanged by any subagent)
`__init__.py` 36 · `api_client.py` 314 · `api_errors.py` 133 · `assertions.py` 181 · `constants.py` 210 · `factories.py` 298 · `fixtures.py` 548 · `test_users.py` 106 · `types.py` 219

**`test_suite/` — 23 files, 7,947 lines, 140 tests**

Queue A (difficulty index) — 13 files, 64 tests:
`test_cost_share_determination.py` 215/5 · `test_per_diem_claim_pricing.py` 188/5 · `test_waitlist_priority.py` 113/3 · `test_eligibility_redetermination.py` 177/4 · `test_resident_dimensions.py` 116/3 · `test_waitlist_offer_cycle.py` 109/3 · `test_survey_cascade.py` 135/4 · `test_discharge_cascade.py` 115/4 · `test_validation_priority.py` 165/5 · `test_bed_capacity_boundaries.py` 272/7 · `test_cross_entity_prerequisites.py` 293/7 · `test_claim_temporal_exclusivity.py` 187/5 · `test_conservation_invariants.py` 321/9

Queue B (corner index) — 9 files, 76 tests:
`test_corner_entities.py` 510/12 · `test_corner_state_machines.py` 682/11 · `test_corner_calculations.py` 818/10 · `test_corner_validations.py` 893/10 · `test_corner_endpoints.py` 711/6 · `test_corner_consistency.py` 138/1 · `test_corner_errors.py` 884/16 · `test_corner_rbac.py` 432/5 · `test_corner_cross_cutting.py` 413/5

Plus `conftest.py` 60 (unmodified since Stage 1).

## Coverage against the two design indices
- **Queue A: 23/23 difficulty instances, all with >=2 tests** (64 tests, floor was 46). Nothing skipped.
- **Queue B: 67/69 non-stub corner instances, 76 tests.** None of the 24 `excluded_because:` stubs was translated.
- Machine-verified: every test carries exactly one `Design:` line; all 140 tags resolve to a real instance with matching section/rule_id; no dual-tagged, untagged, or stub-tagged test; every docstring carries a `Per the PRD:` citation.

## Instances skipped (2, both queue B / entities)
- `entity_income_record_zero_amount_rejected` — the instance requires `monthly_amount_cents: 0` -> 422, but the PRD only says the gross "must not be negative"; the strictly-positive rule belongs to the trust-fund `amount_cents`. Outcome not derivable.
- `entity_waitlist_entry_body_foreign_keys_not_found` — the instance requires `ERR_APPLICANT_NOT_FOUND` when both body FKs are unknown, but the PRD's pinned body-FK order resolves `care_unit_id` first, so the answer is `ERR_CARE_UNIT_NOT_FOUND`. The distinguishing assertion is contradicted.

## PRD-first reconciliations worth flagging
- `readmission_blocked_at_exactly_thirty_bed_hold_days`: dropped the instance's `bed_hold_started_on == null` assertion — the PRD states explicitly it is *not* cleared at readmission. All other assertions kept (409 on the 31-day span, 200 on the 30-day span, `bed_hold_days_used` 30).
- Subagents made similar single-assertion corrections: denial branch is 201 not 200; `paid_amount_cents` is null (not 0) on a VOIDed claim; `adl_dependency_count` capped at 6 and `adl_support_level` `MODERATE` (design used out-of-enum values); first-determination `delta_from_prior_cents` literals dropped as non-derivable; exact-timestamp literals replaced with prefix matches because the PRD mints three fractional digits.

## Verification performed
`python3 -m py_compile` clean on all 32 files; `pyflakes` clean (two unused imports found and removed); an AST pass confirms every `fx.*`, `f.*`, `api.*` and `from test_helpers.* import` name exists in the helper modules; `pytest --collect-only` collects **140 tests, 0 import errors**. No test references implementation code, and nothing under `workspace/implementation/` was read or written. No server was started and no `.md` files were created.

## Step 6: Generate implementation (subagent) — 2026-09-03T13:04:00.000Z

Launched concurrently with Step 5 in a single assistant message, so the impl generator had physical
isolation from `test_suite/` (the directory did not exist when it started).

Verbatim subagent summary:

Implementation complete and verified.

## Files written
`/home/ubuntu/github/CodingPRD/tasks/task_2557_state_veterans_home_admission_per_diem/workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `app.py` | 74 | `create_app()`, 6 blueprints under `/svh`, ApiError/404/405/HTTPException/Exception handlers, `app.run(host="0.0.0.0", port=$PORT)` |
| `store.py` | 193 | In-memory dicts (12 collections), logical clock frozen at `2026-08-01T00:00:00.000Z`, ISO-8601 3-digit helpers, `new_record`/`touch`/`touch_once`/`order_key`, `_seq` tie-break |
| `common.py` | 350 | 7 roles, 47-entry `ERROR_STATUS` map, `meta`/`response_type`/`data` envelope, `api_request_id` = `req_`+20 alnum, pagination, field validators |
| `calc.py` | 551 | All pinned constants, `round_half_up` (Decimal ROUND_HALF_UP), 11 derivations (bed counts, posture, priority class/score, acuity, balances, governing determination, survey score/outcome), 12 serializers |
| `services.py` | 604 | Queue recomputation, decert/reinstatement cascades, cost-share 10-step waterfall, census classification, claim attribution/pricing, `census_run` (5 pinned steps + 8 counters), ledger posting |
| `routes_homes.py` | 284 | 10 endpoints |
| `routes_applicants.py` | 481 | 9 endpoints |
| `routes_residents.py` | 392 | 10 endpoints |
| `routes_finance.py` | 313 | 9 endpoints |
| `routes_claims.py` | 350 | 8 endpoints |
| `routes_ops.py` | 37 | 2 endpoints (clock, census-run) |
| `start.sh` | 13 | Foreground `exec python3 app.py`, `PORT` from env (default 10000), binds 0.0.0.0, pip install only when flask is missing (avoids per-test-reboot contention) |
| `requirements.txt` | 1 | `Flask>=2.2.0` |

3,643 lines of Python total.

## Endpoint coverage
Programmatically diffed Flask's `url_map` against the SCAFFOLD `endpoints:` block: **48 implemented = 48 declared (21 GET / 27 POST), zero missing, zero extra.**

## Verification
- `python3 -m py_compile *.py` -> COMPILE_OK.
- Boot on port 18557, then a 30-step end-to-end smoke run: home -> unit -> applicant -> eligibility (CLASS_1, score 1321) -> waitlist -> assessment/submit -> admission APPROVED -> care plan author/activate (review_due 2026-10-18) -> income declare/verify -> PROVISIONAL cost share (TIER_2, bands 40000+39050 = 79050) -> two census runs (13 then 30 days, 1 PNA credit, 1 skipped cost-share debit) -> clock set -> claim open (31 resident days x 11857 = 367,567) -> submit -> adjudicate PAID -> correct (generation 1) -> trust-fund deposit/reverse -> hospitalize/readmit -> survey IMMEDIATE_JEOPARDY decert cascade -> discharge. Plus error paths: SoD 403, `limit=0` 422, unknown resident 404, wrong-owner representative 403. All 30 checks passed.
- Second smoke pass on redetermination and offer cycles: INELIGIBLE -> reopen without amendment 409 -> reopen amended lands ELIGIBLE with `redetermination_count` 1 and `version` +2 in one call; stale OCC 412; ClinicalAssessor self-decide 403; DENIED returns 201 with `data: null` and cancels every live entry; nightly checkpoint issued an offer, then expired it 8 days later back to ACTIVE with `declined_offer_count` 1 (`ERR`-free, correct counters). Confirmed `GET /svh/applicants` correctly 405s (no such collection route in the scaffold).
- Persistence scan: no `open()`, no sqlite/pickle/json dump, no `/tmp` use, no seeding — storage is dicts only.
- Teardown: killed only PID 38075 (resolved via `lsof -t -i :18557 -sTCP:LISTEN`); no pattern kill was used. `__pycache__` removed.

One spec ambiguity I resolved deliberately: PRD §3.9 step 2/3 say postings are made "per in-scope resident" (step 1's scope admits a just-discharged resident for their tail window), while the SCAFFOLD endpoint description says "every non-DISCHARGED resident ... credit each such resident". I restricted PNA credit and cost-share debit to non-DISCHARGED residents, which also keeps the checkpoint consistent with the manual trust-fund endpoint's `ERR_RESIDENT_STATE_INVALID` on a discharged resident. Census-day materialisation still follows the PRD's richer tail-window rule.

## Step 7: Run tests and iterate (long-lived subagent) — 2026-09-03T13:19:00.000Z

Orchestrator verification: all 8 `workspace/implementation/results.{1..8}.json` exist on disk
(timestamped 13:02) and each reports `passed=140 total=140 failed=0 errors=0 skipped=0`.
Sweep was run under `setsid nohup` per the anti-reaping requirement; no reaping pattern observed.

Verbatim subagent summary:

Clean sweep achieved.

## Summary

**Iterations run:** 2. Iteration 1 baseline: 134/140 in all 8 rounds, 6 unique failures, all deterministic (each failed in 8/8 rounds — no flakiness anywhere in the suite). Iteration 2: **140/140 in all 8 rounds** (`results.1.json` ... `results.8.json`, all on disk, timestamped 13:02).

**Tests deleted:** none. All 6 failures traced to either a PRD-silent *format* detail or a test-setup violation of a PRD rule, not to unfair assertions.

**Fixes applied to `test_suite/`** (`test_helpers/` needed no changes — the fixtures were faithful; the bugs were in per-test setup):

- `test_suite/test_waitlist_offer_cycle.py::test_first_nightly_run_offers_the_bed_with_a_seven_day_window` — STEP 1c partial coverage. PRD pins the *instant* ("stamps `offer_expires_at` at the current logical clock plus a seven-day offer window") but names a fractional-digit format only for `api_request_timestamp`, `created_at` and `updated_at` (PRD §2.2/§2.4); `offer_expires_at`'s serialization is PRD-silent, so `...T00:00:00Z` and `...T00:00:00.000Z` are both faithful. Kept the instant assertion, dropped the format claim by switching `== "2026-08-08T00:00:00Z"` to `.startswith("2026-08-08T00:00:00")` — the same form the sibling corner test `test_corner_endpoints.py:194` already used.
- `test_suite/test_discharge_cascade.py::test_the_next_nightly_run_offers_the_freed_bed_with_a_seven_day_window` — identical format-silence collapse on `2026-08-17`; same prefix fix.
- `test_suite/test_corner_endpoints.py::test_census_run_keeps_daily_and_monthly_idempotency_apart` — test bug. It called `fx.census_run(api, "2026-08-02", ...)` while the logical clock still read `2026-08-01`, and PRD §2.5 requires a `through_date` in the future to be rejected with `ERR_DATE_OUT_OF_RANGE` (409). Added the missing `fx.set_clock(api, "2026-08-02T00:00:00Z")`. The implementation's check is PRD-required and was left intact.
- `test_suite/test_corner_errors.py::test_each_recognition_action_moves_the_home_from_its_one_legal_standing` — same test bug on `effective_date`: the test supplied `2026-08-02` / `-03` / `-04` against a clock at `2026-08-01`. Added `fx.set_clock(api, "2026-08-04T00:00:00Z")` after the fixture so every supplied date has already passed, preserving the test's real subject (the GRANT/SUSPEND/RESTORE standing ladder and the mismatched-action 409).

**Fixes applied to `implementation/`:**

- `workspace/implementation/routes_finance.py`, cost-share determination handler — `delta_from_prior_cents` was computed as `monthly_cost_share_cents - (prior or 0)`, so a *first* determination for a resident-month reported its entire share as the delta. PRD §3.7 states it is "...less the `monthly_cost_share_cents` of the prior governing determination for the same resident and the same `effective_month`, **or 0 when this is the first determination for that resident-month**". Changed to return `0` when no prior governing row exists. This fixed both `test_provisional_determination_counts_unverified_income_and_prorates` (141445 vs 0) and `test_second_determination_for_a_month_is_a_new_immutable_row` (42750 vs 0) — the superseding-row case was already correct and is unaffected.

## Step 8: Finalize PRD (subagent) — 2026-09-03T13:23:00.000Z

Step 8 was NOT skipped: Step 7 applied 1 `implementation/` fix and 4 `test_suite/` fixes, so the
skip condition (zero iterations beyond baseline) did not hold.

Verbatim subagent summary:

`/home/ubuntu/github/CodingPRD/tasks/task_2557_state_veterans_home_admission_per_diem/workspace/PRD_FINALIZED.md` written.

## Line counts
- `PRD.md`: 488 lines — `PRD_FINALIZED.md`: 488 lines — **0.0% line delta** (one line revised in place, +3 sentences of prose).

## Changes
- **§2.4 (Common Record Properties and Version Semantics) — revise — extended the `created_at` format sentence so that every other server-stamped instant-valued field (`listed_at`, `offer_expires_at`, `activated_at`, `submitted_at`, `adjudicated_at`, `current_utc`) is pinned to the same ISO 8601 UTC / exactly-three-fractional-digits / trailing-`Z` form, with an explicit carve-out that date- and month-valued fields keep `YYYY-MM-DD` / `YYYY-MM`** — `implementation/store.py:47` (`format_datetime`), used at `services.py:508` for `offer_expires_at`.

## Per-edit pre-edit search log

**Edit 1 — §2.4 timestamp serialisation**
- (a) **Subject identified:** the wire format of instant-valued fields the server mints from the logical clock — triggered by the two Step 7 items that collapsed `offer_expires_at == "...T00:00:00Z"` into `.startswith("...T00:00:00")` because PRD §2.2/§2.4 named a fractional-digit format only for `api_request_timestamp`, `created_at` and `updated_at`.
- (b) **Impl paths enumerated (read/grepped):** `grep -rn "format_datetime\|now_iso()" implementation/*.py` -> single formatter `store.py:47-52` (always `%03d` millis + `Z`); `store.py:131 now_iso`; `store.py:149-153 new_record` (`created_at`, `updated_at`); `store.py:159 touch` (`updated_at`); `common.py:99` (`api_request_timestamp`); `services.py:508` (`offer_expires_at = format_datetime(clock + 7d)`); `routes_applicants.py:270` (`listed_at`); `routes_residents.py:226` (`activated_at`); `routes_claims.py:312/335` (`submitted_at`, `adjudicated_at`); `routes_ops.py:18` and `services.py:568` (`current_utc`). Also enumerated the *date-valued* siblings so the new sentence would not swallow them: `format_date`/`f_date` fields (`review_due_date`, `bed_hold_started_on`, `service_date`, `last_census_date`, `admission_date`, `discharge_date`, `survey_date`, `plan_date`, `recognition_effective_date`, `last_survey_date`) and month fields (`effective_month`, `claim_month`). Also checked `services.py:520-522`, which compares `now_iso()` against the stored `offer_expires_at` string — identical formats, so the PRD's "strictly past" rule stays exact.
- (c) **Wording adjustment made:** used the open-ended "Every other instant-valued field the server stamps from that clock ... including ..." rather than a closed list, so any instant not named is still covered; and appended the explicit "Fields that hold a calendar date or a month keep their `YYYY-MM-DD` or `YYYY-MM` form instead" clause, because without it a fresh implementer could over-apply the millisecond form to `review_due_date`/`service_date`/`last_census_date` and diverge from `format_date`.

## Step 7 items that required **no** PRD edit
- **`test_corner_endpoints.py::test_census_run_keeps_daily_and_monthly_idempotency_apart`** — pure fixture bug (missing `set_clock`). PRD §2.5 already pins "a `through_date` that lies in the future ... is rejected with `ERR_DATE_OUT_OF_RANGE`", and §3.9 repeats it; `routes_ops.py:33-34` matches, and it resolves the body FK `veterans_home_id` before the date check, consistent with ladder rungs 5 -> 14.
- **`test_corner_errors.py::test_each_recognition_action_moves_the_home_from_its_one_legal_standing`** — pure fixture bug (missing `set_clock`). PRD §2.5 already names `effective_date` among the future-rejected fields; `routes_homes.py:189-203` evaluates the standing precondition (`ERR_HOME_RECOGNITION_STATE_INVALID`, rung 8) *before* the date check (rung 14), exactly as §2.11 orders.
- **`routes_finance.py` `delta_from_prior_cents` fix** — this was an impl bug against an already-determinate PRD sentence, not a PRD silence. §3.7 states "...or 0 when this is the first determination for that resident-month", and the fixed code (`routes_finance.py:223,237-241`) reads `calc.governing_determination(resident_id, effective_month)` *before* inserting the new row; that selector (`calc.py:256-262`) is FINAL-outranks-PROVISIONAL then greatest `created_at`, i.e. §3.7's governing rule verbatim, and returns `None` exactly when the resident-month has no determination. No wording change needed.

## Step 9: Complete PRD (three sequential file-partitioned subagent passes) — 2026-09-03T13:47:00.000Z

Orchestrator decision (recorded per the autonomy rule): Step 9 was run as **three sequential
file-partitioned passes** over a single `PRD_COMPLETED.md`, rather than one subagent scanning all
3,631 lines of `implementation/` at once. A single-pass scan of an implementation this large has
previously collapsed into a no-op (PRD_COMPLETED byte-identical to its source, meaning the scan
never really ran). The orchestrator seeded `PRD_COMPLETED.md` from `PRD_FINALIZED.md` itself
(`cp`, 488 lines) and each pass edited it in place with surgical `Edit` calls, forbidden from
rewriting the whole file (truncation guard) and forbidden from reverting earlier passes.

Partition:
- Pass 1 — `app.py`, `store.py`, `common.py`, `calc.py` (envelope/meta, `api_request_id`, pagination,
  filters, ordering, logical clock, timestamp/date formats, id shape, version semantics, validation
  ladder type rules, rounding, constants, 11 derivations, 12 serializers).
- Pass 2 — `routes_homes.py`, `routes_applicants.py` + the waitlist/offer/survey-cascade parts of
  `services.py`.
- Pass 3 — `routes_residents.py`, `routes_finance.py`, `routes_claims.py`, `routes_ops.py` + the
  cost-share / census / claim-pricing / checkpoint / ledger parts of `services.py`.

Aggregate: **488 -> 490 lines, 112,157 -> 128,248 chars (+16,091, +14.3%)**; 58 edits total —
41 ambiguity-pins, 17 mismatch-revisions. Verified by orchestrator: `PRD_COMPLETED.md` is not
byte-identical to `PRD_FINALIZED.md`, retains all five `## ` headings, and still ends on the final
§5 error-table row (`| ERR_PNA_RESERVE_BREACH | 409 |`). No file under `implementation/`,
`test_suite/` or `test_helpers/` was modified after the clean 13:02 sweep (latest code mtime 12:57),
so the 8/8 x 140/140 result still describes the artifacts on disk.

### Pass 1 verbatim summary

Pass 1 complete. `PRD_COMPLETED.md` edited in place; all five `## ` headings intact, file still ends on `| ERR_PNA_RESERVE_BREACH | 409 |`, and the §5 table still carries all 47 rows.

**Lines: 488 -> 490 (+2). Chars: 112,157 -> 118,908 (+6,751).**
**Counts: 11 ambiguity-pins, 3 mismatch-revisions (14 edits total).**

Changes:

- §2.1 — revise — mismatch — `ERR_UNAUTHENTICATED` also fires on a header present but empty, and the role comparison is exact/case-sensitive (`common.py:126-131`)
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly twenty uppercase-alphanumeric characters (24 total) (`common.py:91-95`)
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall-clock, so responses between two clock settings share one instant (`common.py:98-99` -> `store.py:131`)
- §2.3 — insert — ambiguity — a supplied `limit`/`offset` that is not a canonical base-ten integer literal (empty, fractional, non-numeric, zero-padded) is `ERR_INVALID_REQUEST` (`common.py:283-307`)
- §2.3 — insert — ambiguity — every ordering carries an implicit insertion-order tie-break following the direction of the last declared key; `id` is never a sort key; enum "ascending" means lexicographic on the member spelling (`store.py:187-193`, `calc.py` `order_key` users, `routes_homes.py:96`)
- §2.3 — insert — ambiguity — filters are exact string equality; empty value = filter absent; enum/id filter values are unvalidated and simply match nothing (200 + empty array); `claimed`/`reversed` accept `true|false|1|0` case-insensitively; date/month filters must parse; undeclared query params ignored (`common.py:310-344`, `routes_claims.py:89-110`)
- §2.4 — insert — ambiguity — `id` is a canonical lowercase hyphenated v4 UUID from one generator for all entity types (`store.py:150`)
- §2.4 — insert — ambiguity — every named field is always present in the serialised record, `null` when unset, never omitted; nothing unnamed is serialised (`calc.py:325-551`)
- §2.4 — insert — **mismatch (most significant)** — `version`/`updated_at` collapse per request: however many hops touch one record, its `version` advances by exactly 1 per request; the §3.2 redetermination double-increment is the one stated exception (`store.py:175-184` `touch_once` vs. `routes_applicants.py:207,220` plain `touch`)
- §2.5 — insert — ambiguity — `current_utc` is the sole `data` field; `to_iso8601` accepts `T`-or-space separator, optional seconds, 1-6 fractional digits, `Z`/`+-HH:MM`/`+-HHMM`/no zone (read as UTC), else 422; the clock may move backwards (`store.py:15-44`, `routes_ops.py:12-18`)
- §2.8 — revise — mismatch — the hop-by-hop narration fixes *which* records move, not how many times each counter ticks (per the §2.4 collapse) (`services.py:113-127`)
- §2.11 rung 3 — insert — ambiguity — strict type checking (no bool-for-int, no numeric strings); explicit `null` == absent; **unknown body keys ignored, not rejected**; absent/zero-length body = empty object; non-object or unparseable JSON = 422; `Content-Type` never a ground for rejection (`common.py:143-234`)
- §3.3 — revise — mismatch — dropped the false claim that `created_at` is unique per row; ties on all three queue keys resolve by earlier persistence (`services.py:67-76`)
- §3.3 — insert — ambiguity — `acuity_points` is not floored at zero; a behavioural-risk-only assessment carries -30 (`calc.py:182-188`)

Cross-checked with no change needed: all 47 entries of `ERROR_STATUS` match the §5 table exactly; every constant in `calc.py:17-71` is already pinned in §2.9/§3.3/§3.7/§3.8/§3.9; all 12 serialiser field sets are already fully named by §3 (including `CostShareDetermination` correctly omitting `updated_at`/`version`); `round_half_up`/`apply_bps`, `operational_posture`, the bed-count trio, `governing_determination`, `mirrored_cost_share`, `payable_rate_for`, `census_day_claimed` and `survey_outcome` all match their PRD passages as written.

### Pass 2 verbatim summary

Pass 2 complete.

**File integrity**: 490 lines before -> 490 after (all edits were in-paragraph); 118,908 -> 122,192 bytes (+3,284). All five `## ` headings present, §5 table still 47 error rows, file still ends on `| ERR_PNA_RESERVE_BREACH | 409 |`.

**Counts**: 22 edits — 16 ambiguity-pins, 6 mismatch-revisions.

- §3.1 — revise — mismatch — a home registered directly as `SUSPENDED` reads `recognition_suspended_reason` = `UNIT_DECERTIFIED` at creation, not null — calc.py:152 / routes_homes.py:163
- §3.1 — revise — mismatch — home `last_survey_date` is the *most recently recorded* survey's date and is overwritten even by an earlier `survey_date`, not a max — routes_homes.py:276
- §3.1 — insert — ambiguity — a manual `SUSPEND` also releases the voided drafts' census days (hop-4 semantics) — routes_homes.py:209 / services.py:97
- §3.1 — revise — mismatch — `FROZEN` blocking new waitlist entries is enforced via `certification_status`, so the rejection is `ERR_UNIT_NOT_CERTIFIED`, not a posture error — routes_applicants.py:247
- §2.3 — insert — ambiguity — a home's care units order adds `created_at` ascending as a third key — routes_homes.py:96
- §2.3 — insert — ambiguity — a unit's waitlist entries order adds `created_at` ascending after `queue_position` — routes_homes.py:139
- §3.2 — insert — ambiguity — filing never consults the home's `recognition_status` — routes_applicants.py:130
- §3.2 — insert — ambiguity — omitting `review_note` rewrites `decision_note` to null — routes_applicants.py:201
- §3.2 — insert — ambiguity — missing-amended-evidence `ERR_APPLICANT_STATE_INVALID` precedes `ERR_REDETERMINATION_LIMIT` — routes_applicants.py:186-193
- §3.3 — insert — ambiguity — snapshots are re-read only for candidate entries; terminal entries keep their last snapshot — services.py:61
- §3.3 — insert — ambiguity — a queue recomputation rewrites `queue_position`/snapshots without incrementing those entries' `version` — services.py:52
- §3.3 — insert — ambiguity — a second placement still increments the applicant's `version` though `status` stays `WAITLISTED` — routes_applicants.py:279
- §3.4 — insert — ambiguity — assessment creation imposes no applicant-status precondition — routes_applicants.py:295
- §3.4 — insert — ambiguity — any `ClinicalAssessor` may submit a draft; no `assessor_user_id` comparison — routes_applicants.py:320
- §3.4 — revise — mismatch — submission bumps the `version` of every unit where the applicant holds a live entry, not only units "whose queue was reordered" — services.py:88-93
- §3.4 — insert — ambiguity — `admission_date` required on both branches; `decision_note` written as null when omitted — routes_applicants.py:356,404
- §3.4 — revise — mismatch — gate order: `ERR_CARE_UNIT_VERSION_STALE` is evaluated before the applicant-`WAITLISTED` check — routes_applicants.py:367-370
- §3.8 — insert — ambiguity — `deficiencies` is required and element shape is validated (`ERR_INVALID_REQUEST`) — routes_homes.py:250-261
- §3.8 — insert — ambiguity — every survey increments the operating home's `version` — routes_homes.py:277
- §3.8 — insert — ambiguity — cascade-cancelled entries also clear `offer_expires_at` and zero `queue_position` — services.py:117-119
- §3.8 — insert — ambiguity — decertification hops 3-4 fire only from a `RECOGNIZED` home (`PROVISIONAL`/already-`SUSPENDED` homes untouched) — services.py:123
- §3.9 — revise — mismatch — checkpoint issues at most one offer per unit per run (not one per free bed), and `expired_offer_count` counts only lapsed offers, never the three-decline `EXPIRED` entries — services.py:492-532

Not changed (impl already uniquely pinned): home/unit/applicant creation defaults and field sets, recognition action legality and `ERR_HOME_RECOGNITION_STATE_INVALID`, care-unit bed validation, all listing roles/filters, waitlist gate order and duplicate rule, queue sort keys, offer window and decline penalty, both admission branches' cascades and 201/null-data shape, survey score/outcome bands and reinstatement cascade.

### Pass 3 verbatim summary

Pass 3 complete. All integrity checks pass.

## Result

- **Lines**: 490 -> 490 (no line-count change; all edits were in-paragraph)
- **Chars**: 122,192 -> 128,248 (**+6,056**)
- **Integrity**: 5 `## ` headings present, §5 table has exactly 47 rows, file still ends on `| ERR_PNA_RESERVE_BREACH | 409 |`, and `cmp` confirms it is **not** byte-identical to `PRD_FINALIZED.md`
- **Counts**: 14 ambiguity-pins, 8 mismatch-revisions (22 edits total)

### Changes

- §2.1 RBAC — insert — ambiguity — a `ResidentRepresentative` must scope the trust-fund transaction *collection* read with `resident_id` == own id; unscoped/foreign -> `ERR_NOT_RESOURCE_OWNER` after rung 3 — routes_finance.py:125
- §2.7 body-FK list — revise — mismatch — the nightly census run also resolves a body `veterans_home_id` (-> `ERR_HOME_NOT_FOUND`) and was missing from the list — routes_ops.py:26
- §3.1 posture gating — revise — mismatch — PRD claimed `RESTRICTED` "permits a transfer in"; impl's transfer demands `certification_status` exactly `CERTIFIED`, so a `CONDITIONAL` target dies at `ERR_UNIT_NOT_CERTIFIED` and only a bed-full certified unit reaches the bed check — routes_residents.py:259-262
- §3.5 authoring — insert — ambiguity — at authoring, only the cited plan's *status* is tested; resident ownership is deferred to activation — routes_residents.py:158-169
- §3.5 re-activation — insert — ambiguity — `activated_at` and the resident's `current_care_level` are re-stamped on the `REVIEW_DUE -> ACTIVE` path, and succession is not re-tested — routes_residents.py:204-239
- §3.5 transfer gates — revise — mismatch — exact-`CERTIFIED` gate; and only a status of exactly `ACTIVE` satisfies the plan requirement (a `REVIEW_DUE` plan yields `ERR_NO_ACTIVE_CARE_PLAN`) — routes_residents.py:259-270
- §3.5 transfer cascade — insert — ambiguity — a transfer revokes no outstanding offer even when the target tightens to `RESTRICTED`, and the home is not touched — routes_residents.py:284-288
- §3.6 bed-hold open — insert — ambiguity — the `admission_date` rule is evaluated before the overlap rule (same rung); no future-date rule on `hospitalization_start_date` — routes_residents.py:302-309
- §3.6 discharge closure — revise — mismatch — closure blocks *recording*; verifying an income record and reversing a posting stay open on a `DISCHARGED` resident — routes_finance.py:184, 291
- §3.7 verification — insert — ambiguity — verification consults no occupancy precondition — routes_finance.py:178-193
- §3.7 waterfall step 8 — insert — ambiguity — `PROVISIONAL` `resident_day_count` is floored at zero for a pre-admission month — services.py:228
- §3.7 reversal — insert — ambiguity — no resident-state and no date precondition; `effective_date` is copied — routes_finance.py:285-315
- §3.9 step 2 — insert — ambiguity — steps 2/3 use a narrower, non-`DISCHARGED` scope than step 1; a zero-PNA home posts nothing and counts nobody — services.py:425, 432-434
- §3.9 step 3 — revise — ambiguity — same scope; the governing selector keys on the clock month, not `through_date`'s month — services.py:449-453
- §3.9 claim opening — insert — ambiguity — `veterans_home_id`/`care_unit_id` pairing is never cross-checked — routes_claims.py:166-171
- §3.9 attribution set — revise — mismatch — days held by a `DRAFT` claim are attributable too; only `SUBMITTED`/`PAID` locks a day — services.py:264-271
- §3.9 single-attribution rule — revise — mismatch — restated in terms of "live" claims — services.py:274-279
- §3.9 submission — revise — mismatch — a fifth gate, `ERR_CENSUS_DAY_ALREADY_CLAIMED`, sits between the unit check and the month-closed check — routes_claims.py:291-297
- §3.9 correction — revise — mismatch — re-attributes days held by *any* non-live claim, not just the target — services.py:311-318
- §3.9 adjudication — revise — ambiguity — a missing `rejection_code` on `REJECTED` is `ERR_INVALID_REQUEST` (422) at rung 3, before the claim path resolves — routes_claims.py:327-328
- §3.9 adjudication — revise — ambiguity — `adjudication_note` is written back to null when omitted (discarding a correction's parked `correction_note`); the home is untouched — routes_claims.py:336, 346-349
- §4 preamble — insert — ambiguity — clock and checkpoint answer 200; the trust-fund reversal answers 201 with the new `REVERSAL` row — routes_ops.py:18, 37; routes_finance.py:315

Notable substantive findings: the DRAFT-holds-no-lock attribution semantics (reachable via two successive corrections of one paid claim) and the transfer-into-a-`CONDITIONAL`-unit contradiction were both real PRD-vs-impl mismatches rather than mere silences.

---

## Pipeline complete — 2026-09-03T13:47:00.000Z

All nine steps done. `workspace/PRD_COMPLETED.md` written (490 lines). Final artifact state:
SCAFFOLD trio + worklog.md + test_helpers/ (9 files, 2,045 lines) + test_suite/ (23 files, 140 tests)
+ workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (13 files,
3,631 lines of Python + start.sh + requirements.txt), results.{1..8}.json all 140/140}.
