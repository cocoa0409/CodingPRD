# Worklog — task_2421_residual_property_market_fair_access_plan

## Step 1: Create task directory — 2026-09-02T15:52:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2421_residual_property_market_fair_access_plan` and its `workspace/` subdirectory. Index 2421 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-02T17:40:00.000Z

Task 2421 scaffold is complete and lint-clean.

## Files (all absolute)
- `/home/ubuntu/github/CodingPRD/tasks/task_2421_residual_property_market_fair_access_plan/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_2421_residual_property_market_fair_access_plan/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_2421_residual_property_market_fair_access_plan/SCAFFOLD_CORNER_DESIGN.yaml`

## Final lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2421_residual_property_market_fair_access_plan/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2421_residual_property_market_fair_access_plan/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2421_residual_property_market_fair_access_plan/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     14
  §1.8 instances scanned:     25
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  1068

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## SCAFFOLD.yaml (§1.0–§1.7)
14 entities, 10 state machines, 2 concurrency rules (OCC), 8 calculations, 46 ordered validations, 55 endpoints, 43 error codes, 8 roles, `api_prefix: /fair-plan`. Confirmed top-level keys contain neither `scaffold_difficulty_design` nor `scaffold_corner_design`.

## §1.8 difficulty coverage — 9 rule_ids / 25 instances
dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 3, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 3.

## §1.9 corner coverage — all 9 sections / 79 instances (50 recipes + 29 `excluded_because` stubs)
entities 15/0, state_machines 13/6, calculations 3/9, validations 3/8, endpoints 3/3, errors 5/0, rbac 5/0, complexity_layers 2/3, consistency_model 1/0.

## Verification beyond the lint
- All 43 error codes are asserted by at least one recipe (`not asserted: []`).
- 0 duplicate instance names across both design files; 0 dangling `excluded_because.difficulty_instance` references.
- Field-existence audit of every `Entity.${var}.field` assert against §1.1: previously found one invalid claim, `Policy.improvement_credit_pct`, in `waiver_by_the_raising_inspector_and_bind_by_the_eligibility_reviewer_are_rejected` (Policy has no such field — it is an intermediate in the §1.3 premium formula). Rewritten as an assert over `annual_premium_cents == 607500 + 0 - 60750 - 0`, stating that with `cleared_major_count == 0` the improvement credit is 0 cents so a WAIVED MINOR requirement earns no credit. Re-audit is clean (0 issues).
- Replay checks: bind-prerequisite ordering (property/applicant/producer/declinations/submission/eligibility-review/inspection completion/approved filing before every successful `POST /fair-plan/policies`), ≥3 declinations before every ADVANCE, and rate-filing `/review` approval before every bind — all 0 violations. Every remaining `BOUND` claim was re-checked against the §1.2 note that a bind whose `effective_date <= clock` lands directly in `IN_FORCE`; the surviving BOUND claims are all future-dated (renewal effective 2027-09-01, pre-inception cancel effective 2026-09-15, first-sweep no-op) or refer to `Application.status == BOUND`.

## Design adjudications
- BOUND-vs-IN_FORCE: same-day binds go straight to IN_FORCE, so the declared `BOUND → CANCELLED` edge is only reachable pre-inception. Added `pre_inception_cancellation_of_a_future_dated_bind_leaves_bound_directly` (effective 2026-09-15, clock 2026-09-01, unearned_fraction 1.0000 → unearned 577125 / fee 17314 / refund 559811) and retargeted two grounds refs to `IN_FORCE_to_CANCELLED`.
- `ERR_INSUFFICIENT_DECLINATIONS` had no assert; the corresponding cascading-validation stub was promoted to a full recipe (2 declinations → ELIGIBILITY_HELD → ADVANCE 422 → DECLINE 200).
- Grouped multi-refusal instances in the `errors` section (one shared setup, several 4XX triggers) to close error-code coverage without duplicating long chains.
- `ERR_NO_ASSESSABLE_MEMBERS` reached via a PREMIUM_VOLUME event with all `written_premium_share_pct == 0.00` rather than by withdrawing members; `ERR_UNAUTHENTICATED` via an undeclared role string plus empty `as_user_id`.
- Fixtures pin `dwelling_limit_cents <= replacement_cost` (validation 34) and widen zone caps to 900000000 so validation 43 is only tripped deliberately; second rate filings re-read `CatastropheZone.version` because both filing and approval bump it.
- Negative triggers capture `$.data.error_id` so the lint's negative-test detection suppresses role/payload checks.

## Step 3: Copy shared files — 2026-09-02T17:42:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T17:59:00.000Z

PRD complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2421_residual_property_market_fair_access_plan/workspace/PRD.md`

**Final line count: 469.** Last section heading: `## 5. Error Code Catalogue`. The file ends at a real boundary — the completed 43-row error table, final row `| \`ERR_PAYMENT_AMOUNT_MISMATCH\` | 422 |`, no trailing placeholder, no audit footer. Both withheld design YAMLs and all sibling task directories were left unread.

**Section list**
- §1 Introduction
- §2 Global Specifications (11 subsections): 2.1 Participants/Auth/RBAC · 2.2 API Response Structure (fixed) · 2.3 Pagination and List Ordering · 2.4 Identity, Audit Fields, Version Counters · 2.5 Money, Rates, Rounding · 2.6 Logical Clock, Dates, Window Arithmetic · 2.7 Territory Exposure Posture · 2.8 Segregation of Duties · 2.9 Stale-Version Protection · 2.10 Cascade Discipline · 2.11 Request Validation Order (44-rung ladder)
- §3 Business Logic (9 subsections): 3.1 Plan Foundations · 3.2 Rate Filings and Regulatory Approval · 3.3 Assembling an Application · 3.4 Submission, Eligibility Routing, Underwriting Review · 3.5 Inspection and Condition-Based Remediation · 3.6 Binding, Premium Ladder, Producer Commission · 3.7 Term Maintenance (renewal/cancellation/expiry/sweep) · 3.8 Depopulation · 3.9 Member Assessments
- §4 Endpoint Definitions (4-column, 55 rows)
- §5 Error Code Catalogue (2-column, 43 rows)

**Hard Contract results (all machine-verified)**
- **Contract 1 — Field-Name Coverage: PASS.** All 136 fields across all 14 entities appear as backticked tokens; every enum value across every enum field appears verbatim.
- **Contract 2 — Rule Coverage: PASS.** All 43 distinct scaffold error IDs appear in prose and in §5 with zero HTTP-status mismatches against the scaffold. All 25 named constants are placed (5 rendered as words — `IMPROVEMENT_CREDIT_PER_MAJOR_PCT` "four percent", `IMPROVEMENT_CREDIT_CAP_PCT` "eight percent", `MAX_CREDIT_OFFSET_PCT` "fifty percent", `POLICY_TERM_DAYS` "three hundred sixty-five days", `FEE_LARGE_PCT` "three percent" — each unambiguous and reconstructible). All 55 endpoints present with method + path + description, and per-endpoint authorized roles match the scaffold exactly (0 mismatches). No pseudocode operators (`==`, `>=`, `+=`, `&&`, `||`) survive anywhere in the document; no fuzzy quantifiers.
- **Contract 3 — §3 Path Purity: PASS.** Lines 201–360 contain no backticked token beginning with `/`, no bare HTTP method, and no method+path pair. Paths appear only in §1 (the `/fair-plan` mount) and the §4 table.
- **§2.2 fixed contract:** byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md` (verified by `diff`), sentinels intact.

**Adjudications**
1. §2.11 renders the 46 scaffold validation priorities as 44 rungs: the three `ERR_SEGREGATION_OF_DUTIES` rules are merged into one rung that states their relative order (filing review → requirement waiver → policy binding); the two `ERR_NOT_FOUND` rules stay separate.
2. `version`'s initial value is unstated in the scaffold; the PRD fixes it at 1 with increment-by-one per mutation.
3. Descriptive operation names are used throughout §2 as well as §3 (Contract 3 only polices §3) for consistency.
4. The premium ladder lives in §3.6; §3.4 names the `PROVISIONAL_QUOTE` / `VOLUNTARY_EQUIVALENT` variant inputs and forward-references it — deliberate scattering, reconstruction preserved.
5. On renewal, the successor's `condition_score_at_bind` carries the predecessor's value forward. The scaffold pins `RENEWAL_FINAL` rating to `predecessor.condition_score_at_bind` but never states the successor's own snapshot, and the field is non-null on every policy.
6. `DeclinationRecord` is called out explicitly in §2.4 as the sole entity lacking `updated_at` and `version`, since a blanket "all records carry audit fields" reading would be wrong.
7. §4's intro enumerates exactly the 13 scaffold endpoints coded 201 (including the easily-missed `POST /fair-plan/policies/{id}/renewal`); everything else is 200.

**Orchestrator truncation check (independent of the subagent):** `tail -12` shows the file ending on the last error-table row; `grep '^## '` returns all five expected section headings in order; the §5 table contains exactly 43 `ERR_*` rows. Not truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T19:05:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, so Step 6's implementation generator started before `test_suite/` existed on disk — physical isolation as the skill requires.)

Generation is complete for both queues.

## Files written

`test_helpers/` (9 files): `constants.py`, `api_errors.py` (registers the §5 error→HTTP status map via `set_error_http_status_map`), `types.py`, `test_users.py`, `api_client.py` (`FairPlanApiClient`, all 60 `/fair-plan` endpoints), `assertions.py`, `factories.py`, `fixtures.py` (5 builder tiers + 9 pytest fixtures), `__init__.py`.

`test_suite/` (19 files): `conftest.py`, plus queue A `test_01_variant_divergence.py`, `test_02_combined_formulas.py`, `test_03_nonlinear_lifecycles.py`, `test_04_cascade_chains.py`, `test_05_precedence_pairs.py`, `test_06_inclusive_boundaries.py`, `test_07_entity_dependencies.py`, `test_08_interval_conflicts.py`, `test_09_conserved_quantities.py`, and queue B `test_20_entity_records.py` … `test_28_consistency_model.py`.

## Test counts

106 tests collected. Queue A: 57 tests over 25 difficulty instances (min 2 tests per instance: 6/7/7/8/6/6/6/5/6). Queue B: 49 tests over 49 corner instances, 1 test each (entities 14, state_machines 13, calculations 3, validations 3, endpoints 3, errors 5, rbac 5, complexity_layers 2, consistency_model 1).

## Instances translated vs skipped

- Difficulty (§1.8): all 25 non-stub instances translated across the 9 rule ids (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`). Zero skips.
- Corner (§1.9): 79 instances, 29 marked stub via `excluded_because:` → 50 candidates; 49 translated, **1 skipped**: `Corner/entities/application_create_with_client_supplied_declination_count_rejected` — the PRD nowhere states that an unrecognised request-body field is rejected, so a compliant server may ignore the extra `declination_count` key and return 201. Gap left as a gap.

## Audit results

Every test carries exactly one `Design:` line as the docstring's final block; 0 dangling tags, 0 tags pointing at stub instances, 0 dual-tagged tests. 239 `PRD:` citations, all verified verbatim against `PRD.md` under whitespace normalisation; every test has at least one citation with a ≥8-word distinctive substring. No occurrence of the word "scaffold" anywhere in the emitted code. `compileall` clean, pyflakes clean apart from expected conftest fixture re-export warnings. Pagination meta asserted only via `total_count`/`has_more`/`limit`/`offset` — no use of `total`. Suite was never run against the live server, only `--collect-only`, so the concurrently generated implementation could not influence it.

## Findings worth escalating (design-vs-PRD conflicts, all resolved in the PRD's favour)

1. **422 vs 409.** The difficulty design asserts HTTP 422 for `ERR_ZONE_CLOSED`, `ERR_ZONE_RESTRICTED_INELIGIBLE`, `ERR_MEMBER_NOT_ACTIVE`, `ERR_PRODUCER_NOT_APPOINTED`, `ERR_NO_APPROVED_RATE`, `ERR_POLICY_TERM_OVERLAP`, `ERR_FILING_WINDOW_CONFLICT`; PRD §5 and the §2.11 ladder say 409. Tests assert `error_id` only and let the registered status map cross-check.
2. **Arithmetic error in the design.** A successor term effective 2027-09-01 is given `expiration_date` 2028-09-01, but PRD says effective + 365 days, which is 2028-08-31 (2028 is a leap year). Asserted `shift_date(..., 365)` instead of the literal.
3. **Four design/factory key mismatches** in the corner design: a `SMOKE_ALARMS` requirement code that is not in the PRD enum (used `ELECTRICAL_UPDATE`/MINOR); `declination_count` asserted as 3/1 on never-submitted DRAFTs (PRD initialises it to 0); `review_note` sent as the filing-review body key where PRD says `note`; `waiver_reason` sent where PRD says `reason`.
4. **`validations[priority=N]` numbering in the corner yaml is offset** from the real 44 rungs of §2.11, so priority numbers there are not usable as rung indices.
5. **Process note:** shared `/tmp/compact.py` and its outputs were clobbered mid-session by a concurrent sibling agent writing a different task's design. Worked around with task-unique `/tmp/t2421_*` renderers; any future runner should namespace scratch files per task.

## Step 6: Generate implementation — 2026-09-02T19:05:00.000Z

Implementation complete and validated end to end.

## Files written
`/home/ubuntu/github/CodingPRD/tasks/task_2421_residual_property_market_fair_access_plan/workspace/implementation/`

| file | lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 46 |
| `db.py` | 98 |
| `errors.py` | 74 |
| `lookup.py` | 63 |
| `middleware.py` | 52 |
| `response.py` | 77 |
| `util.py` | 110 |
| `validate.py` | 213 |
| `routes/__init__.py` | 30 |
| `routes/common.py` | 27 |
| `routes/ops.py` | 88 |
| `routes/registry.py` | 282 |
| `routes/intake.py` | 359 |
| `routes/inspections.py` | 204 |
| `routes/rates.py` | 123 |
| `routes/policies.py` | 302 |
| `routes/takeouts.py` | 117 |
| `routes/assessments.py` | 184 |
| `services/constants.py` | 107 |
| `services/zone.py` | 52 |
| `services/ratefiling.py` | 41 |
| `services/premium.py` | 99 |
| `services/commission.py` | 33 |
| `services/refund.py` | 53 |
| `services/eligibility.py` | 46 |
| `services/inspection.py` | 61 |
| `services/policy.py` | 122 |
| `services/assessment.py` | 150 |
| `services/__init__.py` | 0 |
| **total** | **3224** |

## Endpoints
**55** Flask rules under `/fair-plan`, exactly matching PRD §4 / SCAFFOLD §1.5 (verified by enumerating `url_map`). List-filter query params match the SCAFFOLD `input:` lists for all 13 list endpoints. Storage is in-memory dicts only (`db.Store`, 14 collections); zero seeding, zero disk I/O; `PORT` is read from the environment (which the runner injects), so `start.sh` re-launches cleanly per test.

## Verification
Three ad-hoc HTTP smoke suites (~190 assertions, kept outside the deliverable in `/tmp`) exercised all 55 endpoints: full happy path (application → declinations → submission → eligibility → inspection with conditions → evidence/clearance/waiver → bind → take-out offer/withdrawal/acceptance → assessment event → allocation run → invoicing → payments → SETTLED), plus renewal, short-rate and pro-rata cancellation, all four sweep jobs, RESTRICTED/CLOSED zone gates, cat surcharge, minimum-premium floor, filing quiet window and supersession, inspection FAIL path, declination aging/dedup, allocation re-run and event cancellation, producer suspend/reinstate/terminate, all three SoD checks, OCC 412s, pagination/envelope shape, and every negative-precedence ordering. 17 initial "failures" were all traced to wrong expectations in my throwaway test scripts, each re-checked against PRD text and confirmed the implementation is right (notably: refund fee tiers are chosen from `unearned_premium_cents` so a short-rate 74121 lands in the 5,000-cent tier; commission clawback uses the unearned *fraction*, not the 0.90-adjusted money; ownership is gated on exactly the seven POST operations named in §2.1 and never on reads; an undeclared `X-User-Role` is 401 not 403; vacancy eligibility (rung 33) precedes inspection staleness (rung 34)).

## Interpretation decisions where the PRD was ambiguous
- `api_request_timestamp` uses real wall-clock UTC; every business/audit timestamp uses the logical clock. A private `_seq` counter breaks `created_at` ties for the default ascending sort.
- Half-up rounding is `Decimal.quantize(ROUND_HALF_UP)` (away from zero), which matters for the negative condition adjustments (−0.10/−0.05).
- Body FK existence resolves in the ladder's listed order, so `applicant_id` is checked before `property_id` on `POST /applications`.
- A non-existent producer on `POST /applications` yields `ERR_PRODUCER_NOT_APPOINTED` (409), since `producer_id` arrives via `X-User-ID`, not the body.
- Inspection `result` must be PASS/PASS_WITH_CONDITIONS/FAIL; PASS-with-requirements and PASS_WITH_CONDITIONS-without-requirements are rung-3 400s.
- Illegal `MemberInsurer` PATCH transitions → `ERR_INVALID_REQUEST` 400 (the catalogue has no member-status code); same-status pairs are accepted as no-ops and still bump `version`.
- Settlement deducts `credits_consumed` for **every** allocation on the event, including ABATED ones (literal §3.9 wording).
- Each record touched by a cascade gets exactly one version bump per request (deduped via a `touched` set).
- `allocated_total_cents` is always recomputed as Σ`gross_share_cents` over non-ABATED allocations.
- The requirement clear/waive → application cascade is gated on `application.status == "IMPROVEMENTS_REQUIRED"`; inspection completion cascades unconditionally.
- Invoicing enforces `allocated_total_cents == assessable_amount_cents` with `ERR_ASSESSMENT_STATE_INVALID`.
- Sweep jobs run sequentially, so a policy activated in job 1 can also expire in job 2 within the same sweep.
- `naic_code` length is not enforced (rung 3 enumerates no length checks); all `> 0` money/limit constraints are enforced as 400.
- Eligibility `ADVANCE` re-runs the sufficiency test as a gate only; it does not rewrite `declination_count`.
- A renewal does not exclude the predecessor from the term-overlap check (touching endpoints are legal) and the successor inherits the predecessor's `application_id`.
- Query params not named in the SCAFFOLD filter list are ignored; non-404 `HTTPException`s (405, malformed JSON) map to `ERR_INVALID_REQUEST` 400.

## Step 7: Run tests and iterate — 2026-09-02T19:35:00.000Z

All 8 parallel rounds: 106/106.

## Summary

**Iterations run:** 2 (initial 8-round sweep → one fix → confirming 8-round sweep).

**Tests deleted:** none. No test asserted a scaffold-only or PRD-silent rule.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2421_residual_property_market_fair_access_plan/test_suite/test_07_entity_dependencies.py`, `test_identical_offer_from_the_active_carrier_is_created` — changed `validate_success(response)` (implicit 200) to `validate_success(response, 201)`. PRD §4 states verbatim: "Operations that bring a genuinely new resource into existence — … making a take-out offer, or opening an assessment event — return `201 Created`." The implementation returned 201 correctly; the test's expected status was a mis-translation. This is a STEP-2 test bug, not weakened — the assertion is now *more* faithful to PRD (all sibling assertions on offer status, member id, credit units, both policy dimensions and the list `total_count` are untouched).

**Fixes applied to `implementation/`:** none. No implementation defect surfaced.

**Final sweep evidence** (`workspace/implementation/results.N.json`, 8 concurrent rounds under `setsid`, `per-test-server` isolation):

| round | passed/total | duration |
|---|---|---|
| 1 | 106/106 | 321 s |
| 2 | 106/106 | 328 s |
| 3 | 106/106 | 328 s |
| 4 | 106/106 | 322 s |
| 5 | 106/106 | 331 s |
| 6 | 106/106 | 331 s |
| 7 | 106/106 | 329 s |
| 8 | 106/106 | 328 s |

**Notes worth relaying:**
- The only failure found was deterministic (all 8 rounds of iteration 1), so no flakiness was present in this artifact — no load-induced or race-window failures appeared in either sweep.
- Beware of diagnosing from `workspace/sweep.log`: 8 concurrent runners share one file and their `-v` lines interleave mid-line, which made a *passing* test (`test_suspended_producer_cannot_submit_the_application`) appear to be the one tagged `FAILED`. The per-round `results.N.json` files are the only trustworthy source; they named the real failure.
- One latent (currently unexercised) test_helpers defect I noticed but did not need to touch: `test_helpers/factories.py::requirement_waiver_payload` builds `{"waiver_reason": ...}`, whereas PRD §3.5 says the waiver request supplies "a `reason` that is stored as `waiver_reason`". No test uses that factory — both waiver tests inline `{"reason": ...}` — so it is dead code today, but it would fail with `ERR_INVALID_REQUEST` if a future test picked it up.

**Orchestrator verification (independent of the subagent, per the known Step-7 failure mode where a clean sweep is claimed with no artifacts on disk):** all eight `workspace/implementation/results.{1..8}.json` exist (~31 KB each, timestamps 19:30–19:31) and parse as JSON with `passed == total == 106`, `failed == 0` in every round. Sweep is real.

**Step 8 skip condition — NOT met.** Step 7 applied 1 `test_suite/` fix, so the "0 deletions / 0 test_suite / 0 test_helpers / 0 implementation" condition fails and Step 8 runs. The single diff item (take-out offer creation returning 201) is the focus list handed to Step 8 as `<step_7_diff>`.

## Step 8: Finalize PRD — 2026-09-02T19:37:00.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_2421_residual_property_market_fair_access_plan/workspace/PRD_FINALIZED.md` has been produced as an **exact byte-for-byte copy of PRD.md — zero edits**.

## Line counts
- PRD.md: 469 lines
- PRD_FINALIZED.md: 469 lines
- Delta: 0 lines, 0.00%

## Per-change bullets
None. Both `<step_7_diff>` items resolved to PRD-already-determined behavior or a pure fixture bug, so no PRD text is under-determined or mismatched.

## Adjudication of each `<step_7_diff>` item

**1. `test_suite/test_07_entity_dependencies.py::test_identical_offer_from_the_active_carrier_is_created` — `validate_success(response)` → `validate_success(response, 201)`**

- (a) Subject: the HTTP success status returned by resource-creating endpoints, specifically take-out offer creation.
- (b) Impl paths enumerated: `grep -rn "created("` across all of `implementation/routes/` returned exactly 13 callsites — `registry.py:75` (member insurer), `registry.py:163` (cat zone), `registry.py:229` (producer), `intake.py:63` (applicant), `intake.py:94` (property), `intake.py:156` (application), `intake.py:211` (declination), `intake.py:347` (inspection), `rates.py:73` (rate filing), `policies.py:156` (bind), `policies.py:251` (renewal successor), `policies.py:302` (take-out offer), `assessments.py:56` (assessment event). `implementation/response.py:53-54` confirms `created(data) → ok(data, 201)`. Every other route returns `ok(...)` (200).
- Verdict: that 13-item set is in exact one-to-one correspondence with PRD §4's enumerated 201 list ("admitting a member carrier, defining a territory, registering a producer, an applicant, a property or a rate filing, opening an application, recording a declination, ordering an inspection, binding a policy, renewing into a successor policy, making a take-out offer, or opening an assessment event"), including the two 201s the test never touched (renewal successor, declination). PRD uniquely determines 201 here; the Step-2 test had simply mis-translated it. **No PRD edit warranted** — patching would only restate existing prose.
- (c) Wording adjustment: n/a (no edit).

**2. Latent, untouched note: `test_helpers/factories.py::requirement_waiver_payload` builds `{"waiver_reason": ...}` vs PRD §3.5's `reason`**

- (a) Subject: the request-body field name for the improvement-requirement waiver, and the record field it lands in.
- (b) Impl paths enumerated: `implementation/routes/inspections.py:178-204` (`POST /improvement-requirements/{id}/waiver`) reads `reason = req_string(data, "reason")` — a **required** body field — and writes `requirement["waiver_reason"] = reason` at line 199. Grepped `waiver_reason` / `"reason"` repo-wide across `implementation/`: the only other `waiver_reason` occurrence is `inspections.py:103`, where requirement creation initializes it to `None`; sibling `reason`-taking endpoints (`assessments.py:114` assessment cancellation, `registry.py:257-258` optional producer status-action reason, `takeouts.py:98` offer withdrawal) all likewise read the request key `reason`, so the impl convention is uniform.
- Verdict: implementation matches PRD §3.5 verbatim ("supplying a `reason` that is stored as `waiver_reason`"). This is a `test_helpers/` fixture defect, **not** PRD silence or PRD/impl divergence, and per HARD SCOPE it was also not a Step 7 fix. **No PRD edit.**
- (c) Wording adjustment: n/a (no edit).

## Key finding
Step 7 surfaced no implementation defect and no scaffold-only/PRD-silent assertion, so there is nothing in `<step_7_diff>` that reveals a place where `implementation/` pinned a choice PRD left open. The correct Step 8 patch is genuinely empty; the one latent fixture bug it flags is a `test_helpers/` issue that a Step 9 implementer reading PRD_FINALIZED.md alone would not reproduce.

**Orchestrator verification:** `diff -q PRD.md PRD_FINALIZED.md` reports the files identical; both are 469 lines. The zero-edit outcome is real, and `PRD_FINALIZED.md` exists on disk so Step 9 takes it as its source.

## Step 9: Complete PRD — 2026-09-02T19:46:00.000Z

`PRD_COMPLETED.md` is written. Summary:

## Counts
- **PRD_FINALIZED.md**: 469 lines / 88,867 bytes → **PRD_COMPLETED.md**: 469 lines / 93,413 bytes (**+4,546 bytes, +4,498 chars, 0 new lines/paragraphs/sections**)
- 25 paragraph lines touched, **27 discrete clause edits**: **23 ambiguity-pins**, **4 mismatch-revisions**

## Changes
- §2.1 — revise — ambiguity — blank/whitespace-only `X-User-ID` or `X-User-Role` counts as absent → `ERR_UNAUTHENTICATED` — `middleware.py:31-34`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + 20 upper-case alphanumerics — `response.py:16`
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the host's real UTC clock, not the logical clock — `response.py:22`
- §2.3 — insert — ambiguity — a non-integer `limit`/`offset` is also `ERR_INVALID_REQUEST` — `validate.py:181-186`
- §2.3 — insert — ambiguity — `created_at` ties are broken by server mint order (insertion sequence), earliest first — `db.py:87-91`
- §2.5 — insert — ambiguity — percentage weights are stored/echoed as supplied without re-rounding to 2dp; out-of-range is a schema violation — `validate.py:95-101`
- §2.11 rung 5 — insert — ambiguity — multiple body FKs resolve in the listed order (`applicant_id` before `property_id`) — `routes/intake.py:116-117`
- §3.1 — revise — **mismatch** — `naic_code` five-character length is *not* enforced; only uniqueness is — `routes/registry.py:59-63`
- §3.1 — insert — ambiguity — illegal membership `status` move → `ERR_INVALID_REQUEST` (400); same-status restatement is an accepted no-op; every accepted update bumps `version` — `routes/registry.py:43-98`
- §3.1 — revise — **mismatch** — member-record read is role-gated only; any `MemberInsurerUser` may read any carrier — `routes/registry.py:102-105`
- §3.1 — insert — ambiguity — producer status-action `reason` must be a non-empty string when supplied and is never persisted — `routes/registry.py:256-258`
- §3.1 — revise — **mismatch** — producer-record read is not ownership-gated — `routes/registry.py:279-281`
- §3.2 — revise — ambiguity — the quiet-buffer incumbent is the `APPROVED` filing with greatest `effective_date`, tie → earliest `created_at` — `services/ratefiling.py:39`, `routes/rates.py:94-99`
- §3.3 — insert — ambiguity — a `Producer` whose `X-User-ID` resolves to no producer row gets `ERR_PRODUCER_NOT_APPOINTED`, not 404/403 — `routes/intake.py:120-123`
- §3.4 — insert — ambiguity — re-submission from `ELIGIBILITY_HELD` that still counts <3 raises no error and rewrites anchor/count/quotes/`version` — `routes/intake.py:274-281`
- §3.5 — insert — ambiguity — `PASS` with requirements, or `PASS_WITH_CONDITIONS` with none, is `ERR_INVALID_REQUEST` raised before the path id resolves — `routes/inspections.py:74-79`
- §3.5 — insert — ambiguity — the completion fork writes the application status unconditionally (second inspection overwrites the first's outcome) — `routes/inspections.py:111-120`
- §3.5 — insert — ambiguity — clearance `note` optional, string, not persisted — `routes/inspections.py:163`
- §3.5 — revise — ambiguity — waiver `reason` is mandatory non-empty string — `routes/inspections.py:182`
- §3.6 — revise — ambiguity — inspection-staleness test is one-sided: only >90 days *before* the bind date is stale — `routes/policies.py:131-135`
- §3.7 — insert — ambiguity — successor copies `application_id`/`property_id`/`applicant_id`/`producer_id`/`peril_package`, re-derives `excluded_perils` — `routes/policies.py:241-251`
- §3.7 — insert — ambiguity — the shared application record is untouched by renewal — `routes/policies.py:246-251`
- §3.7 — insert — ambiguity — sweep jobs run in order in one request; a policy can be activated then expired in the same sweep, counting in both counters — `routes/ops.py:39-56`
- §3.8 — insert — ambiguity — `comparable_coverage_flag` is a required boolean (missing/non-boolean → 400; `false` → 422) — `routes/policies.py:262,282`
- §3.8 — revise — ambiguity — withdrawal `reason` is mandatory non-empty string — `routes/takeouts.py:98`
- §3.9 — insert — ambiguity — invoicing total mismatch → `ERR_ASSESSMENT_STATE_INVALID` — `routes/assessments.py:101-103`
- §3.9 — revise — ambiguity — assessment-cancellation `reason` mandatory non-empty; `allocated_total_cents` is recomputed as the non-abated `gross_share_cents` sum (paid total from `INVOICED`) — `routes/assessments.py:114,122-126`
- §3.9 — revise — **mismatch** — the per-carrier allocations page is role-gated, not ownership-gated — `routes/registry.py:127-135`

Notable impl facts already uniquely pinned by the PRD (no edit): the full 55-endpoint surface matches §4 exactly; the §2.11 precedence ladder matches the actual gate order in `bind_policy`, `renew_policy`, `create_offer`, `run_allocation` and `pay_allocation` (including version-before-state on the allocation run, and bind skipping the coverage-limit rung); the premium ladder, refund/fee tiers, commission conservation and allocation waterfall rounding all follow the specified step order.

**Orchestrator verification:** `PRD_COMPLETED.md` exists (93,413 bytes, 469 lines — same line count as its source, so all edits were in-paragraph), ends on the last `ERR_PAYMENT_AMOUNT_MISMATCH` error-table row (not truncated), and still has exactly 5 `##` headings (no new sections added).

**Pipeline complete.** All nine steps ran; Step 9 has written `workspace/PRD_COMPLETED.md`. Final artifact state: SCAFFOLD trio + worklog + `test_helpers/` (9 files) + `test_suite/` (19 files, 106 tests) + `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}` with `results.{1..8}.json` all at 106/106.
