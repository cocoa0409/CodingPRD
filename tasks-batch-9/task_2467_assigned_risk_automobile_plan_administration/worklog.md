# Worklog — task_2467_assigned_risk_automobile_plan_administration

## Step 1: Create task directory — 2026-09-02T21:01:10.901Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2467_assigned_risk_automobile_plan_administration` and its `workspace/` subdirectory. Index 2467 was pre-assigned by the orchestrating pipeline; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-02T22:31:22.946Z

All three artifacts are complete and the scaffold lints clean.

## Deliverables — `/home/ubuntu/github/CodingPRD/tasks/task_2467_assigned_risk_automobile_plan_administration/`

**`SCAFFOLD.yaml`** (2 890 lines, §1.0–§1.7, no design keys)
13 entities / 53 endpoints / 62 error codes / 44 validations / 13 calculations (3 dual-variant) / 10 state machines / 2 concurrency rules / 4 roles. Profile: `quota_allocation` + `compliance_audit`, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy`, topology `flat`, shape `parallel` (money axis × coverage axis), role model `segregation_of_duties`, consistency `immediate`, `expert`.

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (2 243 lines, §1.8) — 9 rule ids × 2 instances = 18: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

**`SCAFFOLD_CORNER_DESIGN.yaml`** (6 944 lines, §1.9) — all nine claim-extraction-guide sections, 82 instances (65 with recipes + 17 `excluded_because` stubs): entities 12, state_machines 17, calculations 15, validations 22, endpoints 6, errors 2, rbac 3, cross_cutting_complexity_layers 4, consistency_model 1. Combined 100 instances / 1 797 structured calls.

## Verification
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared: 53   §1.1 entities: 13
  §1.8 instances: 18   §1.9 instances: 65   Calls scanned: 1797
```
Plus scripted checks: all 62 error ids are triggered somewhere in §1.8/§1.9; zero unbound `${var}`; instance names unique across both files; every stub cites an existing §1.8 instance and carries no `test_recipe`; both `concurrency_rules` write endpoints take their `expected_*_version` and bump `version`; no forbidden concurrency vocabulary.

## Design adjudications
- **Two errors deleted from §1.6** (64 → 62): `ERR_POLICY_ALREADY_ISSUED` and `ERR_NON_RENEWAL_ALREADY_SERVED` were provably unreachable — the priority-6 state check fires first — so their validation rows and catalog entries were removed and the corner instance repointed at `ERR_INVALID_POLICY_STATE`.
- **`DEPOSIT_FLOOR_CENTS` (15 000) never binds** at any territory/class combination; rather than delete a real-world constant, a corner instance asserts the floor is dead (`max()` always takes the 25 % term).
- **Lint negative-test discipline**: one entities instance was renamed to `application_creation_rejects_a_payload_missing_any_declared_input_field` and the deliberate role-violating rescission call now captures `$.data.error_id`, so intentional violations are exempted per the linter's rules instead of being papered over.
- **`selector_policy`** has no row in the claim-extraction guide, so no `claim_type` was invented for it; the selector is covered under `calculations` (queue ordering recomputed between placements, empty-pool deferral) and `endpoints` (`bulk_action`).
- **Fixtures engineered to force the intended branch**: 9000/1000 bps split so one carrier absorbs four placements without becoming overallocated (the only route to `ERR_NON_RENEWAL_QUOTA_EXCEEDED`, which then resets at period closure); a T03 risk against T02-only carriers to get a mixed batch (1 assigned / 1 deferred, still 200); Beacon licensed elsewhere to manufacture overallocation and the −1.0 / 25 000-cent deficiency; `YOUTHFUL_OPERATOR` vs `SENIOR` reclassification to separate points (3 vs 1) from factor (both 1.15).
- **Every asserted literal was recomputed** with decimal/date scripts (e.g. per-line premium 81585/44501/22251 → 148337, tier 2 → 7417 → 155754, deposit 38939; T03 231909 → 9276 → 241185 → 60296; short-rate 91 days → 42715 with balance due 3776; SENIOR re-rate 170587 → 6823 → 177410, additional due 138471).

## Step 3: Copy shared files — 2026-09-02T22:31:45.892Z

Copied `./INSTRUCTION.md` (1424 bytes) to `tasks/task_2467_assigned_risk_automobile_plan_administration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T22:43:45.209Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2467_assigned_risk_automobile_plan_administration/workspace/PRD.md`.

**Size:** 441 lines / 95,517 bytes.

**Sections (all present, complete):**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 Plan Participants and RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination and List Ordering · 2.4 Resource Identity, Audit Fields and Plan Sequences · 2.5 The Logical Plan Clock · 2.6 Territories and Nested Path Resolution · 2.7 Money, Exposure and Rounding Discipline · 2.8 The Deposit and Premium Ledger Invariant · 2.9 Carrier Standing: Performance Score and the Posture Ladder · 2.10 Quota Apportionment by Largest Remainder · 2.11 Optimistic Concurrency on Superseding Filings · 2.12 Cascade Semantics and Derived-State Propagation · 2.13 Validation Order
- §3 Business Logic — 3.1 Bringing a Risk to the Plan · 3.2 Verification, Cure Rounds, and the Eligibility Decision · 3.3 Quota Periods, Assignment Cycles, and Designating a Servicing Carrier · 3.4 Acceptance, Policy Issuance, and Final Rating · 3.5 Claim Handling Standards · 3.6 Complaints and the Two-Examiner Review · 3.7 Mid-Term Change: Reclassification, Non-Renewal, Cancellation, and the Voluntary Exit · 3.8 Carrier Withdrawal and Reassignment of the Book · 3.9 Period Closure, Exposure, and Quota Reconciliation (9 subsections)
- §4 Endpoint Definitions — 4-column table, 53 rows (exact method+path match against scaffold, no missing/extra)
- §5 Error Code Catalogue — 2-column table, 62 rows (every id and status matches scaffold)

**Tail is a real section boundary:** the file ends on the final complete row of the §5 error table (`| \`ERR_DEPOSIT_AMOUNT_INVALID\` | 422 |`). No audit footer, no contract-report block in the file.

```
Field coverage check:
- entities[].fields: 128 required, 128 present, 0 missing
- endpoints[].request_body/input: 63 required, 63 present, 0 missing
- endpoints[].query_params: 16 required, 16 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 44 checked, 44 expressed in prose (§2.13 states the 12-tier order plus the two observable precedence facts: doc gates > deposit gate on certification; complaint freeze > permitted-reason on cancellation), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (quota-reconciliation filing + expected_carrier_version + ERR_STALE_CARRIER_VERSION/412; policy reclassification + expected_policy_version + ERR_STALE_POLICY_VERSION/412; "no other endpoint takes a version field" stated), 0 missing
- state_machines[].transitions: 10 machines / 44 transitions checked, 44 fully expressed with from→to pairs, preconditions and every side effect, 0 missing
- calculations[]: 13 checked, 13 fully expressed in prose (incl. all 3 dual-variant pairs: surcharge estimated/applied, pro-rata/short-rate, POLICY_COUNT/CAR_YEAR_EXPOSURE), 0 missing
- validations[] conditions: 44 checked, 44 matchable to error_id in prose; all 62 error ids appear in §2/§3 narrative, 0 missing
- endpoints[].side_effects / applies_to: 53 endpoints checked, all side-effect lists and all applies_to scopes enumerated (7 carrier-scope ops, 4 producer-scope ops, 3 ERR_CARRIER_NOT_ACTIVE ops, 2 ERR_CARRIER_SUSPENDED ops, 6 ERR_DUPLICATE_IDENTIFIER ops), 0 missing
- entities[].fields[] structured content: 128 checked, 128 reconstructible from prose (types, enum vocabularies, defaults, initial values, MarketRejection's absent updated_at/version), 0 missing
- sibling-branch symmetry: 8 groups checked (CERTIFY/REJECT, INITIAL/REASSIGNMENT acceptance, PAID/DENIED closure, UPHELD/NOT_UPHELD/RETURNED_FOR_FURTHER_REVIEW, PRO_RATA/SHORT_RATE, POLICY_COUNT/CAR_YEAR_EXPOSURE, money-axis refund/balance/exact-equality branches, coverage-axis terminals), 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 809
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 is byte-identical to `section-2.2-response-structure.md` (verified by diff); zero fuzzy/approximating words; zero pseudocode operators (`==`, `>=`, `+=`, `min(`, `round_half_up(`, `AND`/`OR`, etc.) outside the two fixed JSON fences. Per the hard constraint, neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced — all worked examples in the prose (per-line rounding 130537/71202/35601, expense tier boundary, 0.5/0.5 remainder tie, 61539 vs 67693 cancellation, 0.0164/0.2466/0.2630 car-years, −0.1151/2878 reconciliation, 1095-day clean-year boundary) come from `SCAFFOLD.yaml`'s own `precision` and `variants` fields.

**Orchestrator truncation check (per pipeline instruction):** independently verified — 441 lines, tail is the final complete `| \`ERR_DEPOSIT_AMOUNT_INVALID\` | 422 |` table row; §4 table holds exactly 53 endpoint rows matching the scaffold's 53 declared endpoints; §5 table holds exactly 62 error rows. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T00:22:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, per the skill's concurrency requirement; Step 6 returned first but both entries are recorded in skill order.)

Test generation is complete for `task_2467_assigned_risk_automobile_plan_administration`.

## Files written

**Stage 1 — `test_helpers/` (9 files, 2044 lines):** `__init__.py`, `api_client.py` (53 endpoints), `api_errors.py` (62 error ids + HTTP status map), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py` (workflow builders: `bootstrap_plan`, `bring_application_to_certified`, `setup_policy_in_force`, `drive_carrier_to_suspension`, …), `test_users.py`, `types.py`.

**Stage 2 — `test_suite/` (conftest.py + 19 test files, 196 tests):**
- Queue A (difficulty), 13 files, **38 tests**: `test_01`…`test_13` — rating/expense tiers, surcharge step boundary, cancellation settlement, quota reconciliation bases, cure rounds, the two independent policy axes, carrier-exit cascade, complaint-suspension cascade, validation precedence pairs, empty candidate pool, cross-entity gates, interval semantics (half-open terms vs closed cycle windows), headcount conservation.
- Queue B (corner), 6 files, **158 tests**: `test_20_corner_entities` (27), `test_21_corner_state_machines` (29), `test_22_corner_calculations` (16), `test_23_corner_validations_a` (28), `test_23_corner_validations_b` (22), `test_24_corner_platform` (36).

## Coverage audit (scripted against both yamls)

| check | result |
|---|---|
| Difficulty instances (§1.8) | 18/18 covered, **all ≥2 tests**, 0 unknown tags |
| Corner non-stub instances (§1.9) | **65/65 covered ≥1 test**, 0 unknown tags, no test tags a stub |
| Corner stubs | 17 correctly untranslated; all 17 `excluded_because.difficulty_instance` pointers resolve |
| `Design:` tags | exactly one per test, always the last docstring line, correct `Difficulty/<rule_id>/…` or `Corner/<section>/…` form |
| PRD citations | 197 quotations, all verbatim (whitespace-normalized) and ≥8 words |
| Banned patterns | no `pytest.mark`/`skip`/`skipif`/`xfail`, no mention of the design documents |
| Static | `py_compile` OK, pyflakes clean (no undefined names, no unused imports), all `test_helpers` imports resolve |
| Collection | `pytest --collect-only` → **196 tests collected** |

## Instances skipped

**None.** Every difficulty instance and every non-stub corner instance passed the PRD-first two-condition filter — each asserted outcome traces to a verbatim, rule-bearing PRD sentence.

## Two-reader corrections applied

- Relaxed 15 timestamp assertions that pinned a full instant string (`run_at`, `window_start/end`, `effective_date/expiration_date`, `loss_date`, `exit_effective_date`) to date-prefix or field-to-field comparisons. PRD lines 82/84 specify three fractional digits for `created_at`/`updated_at` but say nothing about echo formatting, so `"…T00:00:00Z"` vs `"…T00:00:00.000Z"` was an implementation-legal difference that could have failed a faithful build.
- Lengthened one 7-word PRD quotation in `test_20` to satisfy the ≥8-word greppability rule.

## Design-vs-PRD conflicts resolved in the PRD's favour (worth flagging upstream)

1. Corner recipes assert `Complaint.review_round == 0` at docketing; PRD §3.6 says it begins at 1. Tests assert 1.
2. A reclassification recipe assumes `rating_revision == 0` at issuance; PRD §3.4 says 1. Tests assert 1 → 2.
3. A complaint-loop recipe performs three further-review returns before the refusal; per §3.6 a return is admissible only while `review_round < 3`, so the third return is itself the refused trigger. Test does two returns then the refused third.

Nothing under `workspace/implementation/` was read or written; `SCAFFOLD*.yaml` and `workspace/PRD.md` were read only. The suite was not executed (no server running).

## Step 6: Generate implementation — 2026-09-02T23:16:00.000Z

Implementation complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2467_assigned_risk_automobile_plan_administration/workspace/implementation/`:

- `start.sh` (guarded pip install, `exec python3 app.py`, binds `0.0.0.0:$PORT`, default 10000)
- `requirements.txt` (`Flask>=2.2`)
- `app.py` — factory, 11 blueprints, global RLock in `before_request`, clock-driven non-renewal maturation, `ApiError`/`HTTPException`/`Exception` handlers, `threaded=True, use_reloader=False`
- `store.py` — in-memory `Store` with 13 dicts, `CLOCK_EPOCH = 2026-08-01T00:00:00Z`, id/sequence generators, `new_row`/`touch`
- `errors.py` — HTTP mapping for all 62 PRD error ids plus 3 framework ids
- `envelope.py` — `meta`/`response_type`/`data` envelope, list meta with `limit`/`offset`/`total_count`/`has_more`
- `guards.py` — auth (`X-User-ID`/`X-User-Role`), shape validators, pagination, `need_*` existence lookups, carrier/producer ownership scopes
- `calc.py` — Decimal/Fraction money and exposure math (per-line rounding, expense tiers, deposits, pro-rata/short-rate, car-years, largest remainder, penalties, posture ladder)
- `domain.py` — derivations, carrier selection, cascades/bubble-ups, serialisers
- `routes/` — `carriers.py` (5), `producers.py` (2), `applicants.py` (4), `applications.py` (11), `periods.py` (7), `assignments.py` (4), `policies.py` (7), `claims.py` (5), `complaints.py` (5), `reconciliations.py` (3), `clock.py` (1), plus empty `__init__.py`

## Endpoint count
**53 endpoints** confirmed by enumerating `app.url_map` (excluding `static`, HEAD/OPTIONS).

## Boot confirmation
`bash start.sh` boots from a fresh process and serves on `$PORT` — verified repeatedly, including two back-to-back cold boots on ports 18601/18602 each returning `200` for `GET /plan/carriers`. Storage is in-memory only: no sqlite/JSON/tmp artifacts exist anywhere in the tree, no `open()` calls, and a fresh factory reports all 13 dicts empty with the clock at exactly `2026-08-01T00:00:00Z` (zero seeded entities).

## Behavioural verification
Three throwaway clients in `/tmp` (`smoke2467.py`, `smoke2467b.py`, `smoke2467c.py` — outside the implementation tree) passed every assertion, covering:
- Full intake → MVR → deposit → certification → cycle run → acceptance → issuance chain; rating reproduced the PRD's 246834-cent reclassification fixture exactly.
- Carrier exit → `REASSIGNMENT_PENDING` policy → successor acceptance → predecessor `REASSIGNED` → old carrier `EXIT_COMPLETE`.
- INSURED short-rate cancellation (earned 42715, balance 3776, `BALANCE_DUE_AT_CANCELLATION`).
- Voluntary exit crediting 1.5 units for an underserved garaging territory, applicant re-eligible, application `CLOSED_EXITED`.
- `DEFERRED_NO_CARRIER` when the eligible pool is empty (deferred_count 1, application status confirmed).
- Two-round cure loop with the third `cure-return` → `ERR_CURE_LIMIT_EXCEEDED` 409.
- Negative paths: OCC 412s (`ERR_STALE_POLICY_VERSION`, `ERR_STALE_CARRIER_VERSION`), segregation of duties, complaint freeze blocking cancellation, cancel-reason vs cancel-date precedence, cycle clear-day and outside-period rules, claim overpayment, late-acknowledgement breach with score/posture cascade, quota reconciliations on both bases, period closure, pagination 422s, 401/404 envelopes.

One note: the only earlier "failure" was in my own test script (a cycle scheduled one day after the prior cycle's end, violating the correctly-implemented 2-clear-day rule); no implementation change was needed. The scope constraints were respected throughout — nothing under `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` was read.

## Step 7: Run tests and iterate — 2026-09-03T00:20:30.000Z

Clean 8-round sweep achieved: **196/196 in all 8 parallel rounds**, no flakiness, no `Terminated` in the sweep log.

## Summary

**Iterations run:** 2

**Round 1 result:** 189/196 in all 8 rounds — 7 deterministic failures in 2 clusters (zero flaky tests; every failure reproduced identically in all 8 rounds).

**Tests deleted:** none. Every failing assertion traced to a verbatim, rule-bearing PRD sentence and was uniquely derivable, so all 196 tests were kept.

**Fixes applied to test setup (test layer):**
- `/home/ubuntu/github/CodingPRD/tasks/task_2467_assigned_risk_automobile_plan_administration/test_suite/test_21_corner_state_machines.py`, helper `_claim_on_a_live_policy` — added `set_clock("2026-09-16T00:00:00Z")` before `report_claim`. The helper reported a loss dated 2026-09-16 while the clock was still at the issuance instant 2026-09-15, and PRD §3.7 says the `loss_date` "must fall on or after the policy's `effective_date` and no later than the current clock", so the PRD-faithful implementation correctly returned `ERR_LOSS_DATE_OUTSIDE_TERM`. The helper's own docstring ("reported the day after inception") and the dependent assertions (`acknowledgement_deadline` starts 2026-09-26, i.e. `reported_at` + 10 days = 2026-09-16 + 10) confirm the clock advance was the missing setup step, not a weaker date. This one-line fixture fix cleared all 6 failures in that cluster (`test_a_claim_walks_open_to_acknowledged_to_closed_paid_inside_the_standard`, `test_a_docketed_complaint_opens_on_round_one_with_an_empty_findings_trail`, `test_a_late_acknowledgement_posts_a_breach_and_five_points_to_the_carrier`, `test_closing_a_claim_that_was_never_acknowledged_is_refused`, `test_closing_a_not_at_fault_claim_leaves_the_clean_years_clock_alone`, `test_closing_the_period_zeroes_the_breach_counter_and_credits_ten_points`) — a textbook shared-upstream-fixture bug masquerading as six independent implementation defects.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/policies.py`, cancellation handler — swapped the order of the two priority-10 temporal checks so the `ERR_CANCEL_DATE_OUT_OF_TERM` term-bound test runs before the `ERR_CANCEL_REASON_NOT_PERMITTED` first-sixty-day reason test. PRD states the term-bound rule first ("The `cancellation_effective_date` must lie inside the term … must not be earlier than the current clock") and then introduces the reason rule as a *further* restriction keyed on "how far into the term the cancellation falls" — an elapsed-term position that is only meaningful once the date is known to lie inside the term. A date past expiration therefore reports the date error, which is what `test_a_cancellation_date_past_expiration_or_behind_the_clock_is_out_of_term` asserts. No assertion was weakened and no PRD-required check was removed; the enumeration at §2.13 priority 10 lists which errors share that level, not their intra-level order (levels 6 and 8 are likewise unordered groupings).

**Orchestrator verification of the sweep artifacts (per pipeline instruction):** independently re-checked on disk — all 8 `results.{1..8}.json` present (~61 KB each, written 2026-09-03 00:10), each parsing to `passed == total == 196`; `workspace/sweep.log` ends on a normal runner shutdown (`Results: 196/196 passed, 0 failed, 0 errors, 0 skipped`, duration 359.2 s) with zero occurrences of `Terminated`, confirming the sweep ran under `setsid` and was not reaped.

## Step 8: Finalize PRD — 2026-09-03T00:21:58.413Z

Step 8 was NOT skipped: Step 7 applied 1 `implementation/` fix and 1 test-layer fix, so the skip condition (zero iterations beyond baseline) did not hold.

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_2467_assigned_risk_automobile_plan_administration/workspace/PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 441 lines
- `PRD_FINALIZED.md`: 441 lines (0.00% line delta; one paragraph revised in place — 1 of 441 lines touched, ~0.23% of lines)

## Changes
- **§3.7 (Cancellation, reason-code restriction paragraph)** — *revise* — pinned that the term-bound `ERR_CANCEL_DATE_OUT_OF_TERM` check is evaluated **before** the first-sixty-day `ERR_CANCEL_REASON_NOT_PERMITTED` reason check, noted that §2.13 priority 10 enumerates which errors share business-temporal priority rather than their intra-level order, and adjusted the trailing freeze sentence from "before this rule" to "before both" — `implementation/routes/policies.py:215-222`.

## Step 7 items with no PRD edit
- **Fixture fix (`_claim_on_a_live_policy` clock advance)** — no PRD edit. `implementation/routes/claims.py:35` (`loss_date < policy["effective_date"] or loss_date > db.clock` → `ERR_LOSS_DATE_OUTSIDE_TERM`) and `claims.py:46-47` (`reported_at = clock`, `acknowledgement_deadline = clock + 10 days`) match PRD §3.5 verbatim. This was a pure test-setup bug, not PRD silence.

## Per-edit pre-edit search log

**Edit 1 — §3.7 cancellation check ordering**
- **(a) Subject:** intra-priority ordering of business-temporal (priority 10) checks, specifically the cancellation date-bound rule vs. the elapsed-term reason restriction; plus the general status of §2.13's level-10 list order.
- **(b) Impl paths enumerated:** `grep` for every priority-10 error raise across `routes/*.py`, then read each co-occurrence site.
  - `routes/policies.py:191-256` `cancel_policy` — the Step 7 site: freeze (line 207) → `ERR_CANCEL_DATE_OUT_OF_TERM` (215-220) → `ERR_CANCEL_REASON_NOT_PERMITTED` (221-222).
  - `routes/policies.py:37-124` `issue_policy` — second level-10 co-occurrence: `ERR_POLICY_TERM_INVALID` (56, 58) raised **before** `ERR_POLICY_TERM_OVERLAP` (71), i.e. the reverse of §2.13's list order (overlap is listed 3rd, term-invalid 7th).
  - `routes/periods.py:108,119` `schedule_cycle` — third co-occurrence: `ERR_CYCLE_WINDOW_OUTSIDE_PERIOD` before `ERR_CYCLE_WINDOW_CONFLICT`, again the reverse of the §2.13 list order.
  - `routes/policies.py:271-272` non-renewal, `routes/carriers.py:98` exit notice, `routes/claims.py:36` loss date, `routes/periods.py:32,69,173` — single level-10 check each, so intra-level order is unobservable there.
  - `routes/policies.py:205-208` and `259-270` — confirmed the freeze check (priority 9) still precedes every priority-10 check on both cancellation and non-renewal, so §2.13's existing "Second," consequence paragraph (line 176) stays accurate and needed no edit.
  - `implementation/calc.py:84,86-91` — `FIRST_PERIOD_CANCEL_DAYS = 60` and `RESTRICTED_LATE_TERM_REASONS`, confirming the existing PRD prose on the strict-60 boundary and the permitted set is verbatim-correct.
- **(c) Wording adjustment:** my first draft asserted only that the date rule precedes the reason rule. Because the enumeration revealed two *other* level-10 co-occurrences (`issue_policy`, `schedule_cycle`) that also contradict §2.13's list order, I deliberately phrased the generalisation as a **negative** claim — "§2.13 priority 10 lists which errors share that level rather than fixing their order within it" — instead of any positive intra-level ordering rule. A positive rule ("level 10 is evaluated in listed order", or any re-listing) would have mis-described both off-site paths and created two new mismatches. I also widened the trailing freeze sentence from "before this rule" to "before both" so it covers the date check as well as the reason check, matching `policies.py:207`. I did **not** edit the `issue_policy` or `schedule_cycle` orderings, as neither is a Step 7 diff item (HARD SCOPE).

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (line 280, the §3.7 reason-restriction paragraph); both files are 441 lines, 95,517 → 96,011 bytes.

## Step 9: Complete PRD — 2026-09-03T00:42:26.226Z

`PRD_COMPLETED.md` is written. Summary:

## Counts
- **Source**: `workspace/PRD_FINALIZED.md` — 441 lines, 96,011 chars
- **Output**: `workspace/PRD_COMPLETED.md` — 441 lines, 103,989 chars (**+7,978 chars**)
- 32 lines revised in place; **0 new lines, 0 new sections, 0 new table rows**
- **Ambiguity-pins: 27** · **Mismatch-revisions: 5**

## Changes
- §2.3 pagination — insert — ambiguity — non-parsable `limit`/`offset` also fails as `ERR_INVALID_REQUEST` — `guards.py:227-242`
- §2.3 ordering — insert — ambiguity — the seven ordinal-less lists tie-break on server insertion order, which is also the final tie-break behind the three named ordinals — `domain.py:787-800`
- §2.6 territories — insert — ambiguity — producer `appointed_territories` is duplicate-free; `underserved_territories` defaults to `[]` and alone tolerates repeats — `guards.py:176-195`, `periods.py:24`
- §2.10 apportionment — insert — ambiguity — defines "the current period" (contains-clock → `OPEN` → latest `window_start` → newest row) and the no-period case (total 0, all targets 0) — `domain.py:44-60`, `150-159`
- §2.10 recomputation — insert — ambiguity — read-time derivation means other carriers' `version`/`updated_at` do not move — `carriers.py:53-56`, `applications.py:254`
- §2.12 bubble-up — revise — mismatch — `EXIT_COMPLETE` is re-tested only on reassignment acceptance / cancellation / voluntary exit (not on non-renewal maturation); period closure presupposes ≥1 `ACTIVE` carrier; non-renewal maturation sweeps at the start of **every** request, not just a read of the policy — `domain.py:358-400`, `app.py:52-58`, `assignments.py:111`
- §2.13 pri-3 — insert — ambiguity — unparsable / non-object JSON body fails here; empty body = `{}`; consolidated string-length ceilings for all free-text fields — `guards.py:64-97`, `app.py:86-90`
- §3.1 producer — insert — ambiguity — `status` enum is exactly `ACTIVE`/`SUSPENDED`, default `ACTIVE` — `producers.py:21`
- §3.1 declinations — insert — ambiguity — unknown-code rule precedes the duplicate rule; `rejection_date` itself is unconstrained — `applications.py:127-138`
- §3.1 deposits — revise — **mismatch** — `required_deposit_cents` is also recomputed on MVR verification, and is *not* recomputed at certification — `applications.py:212`, `251`
- §3.1 deposits — insert — ambiguity — zero/negative `amount_cents` reaches the fiscal gate as `ERR_DEPOSIT_AMOUNT_INVALID`, not `ERR_INVALID_REQUEST` — `applications.py:177-182`
- §3.2 decision — insert — ambiguity — `rejection_reason_code` is free-form, 1–100 chars, no enum — `applications.py:225`
- §3.2 CERTIFY — revise — **mismatch** — the `OPEN`-period gate is deferred behind both documentation gates despite its priority-6 error — `applications.py:240-246`
- §3.3 period — insert — ambiguity — `window_end` behind `window_start` is `ERR_INVALID_REQUEST` 422 — `periods.py:26-27`
- §3.3 cycle — insert — ambiguity — same shape error; scheduling never tests the parent period's `status` — `periods.py:102-108`
- §3.3 assignment — insert — ambiguity — `batch_sequence` counts only created rows; deferrals consume no ordinal — `periods.py:188-199`
- §3.4 acceptance — revise — **mismatch** — `ERR_CARRIER_SUSPENDED` is evaluated *before* `ERR_ACCEPTANCE_WINDOW_EXPIRED` — `assignments.py:83-86`
- §3.4 issuance — revise — **mismatch** — real order is term-invalid → overlap → licensed → `policy_number` uniqueness; overlap compares every other policy of the vehicle regardless of `policy_status` — `policies.py:55-78`
- §3.4 exposure — insert — ambiguity — uses the §2.10 current period; 0.0000 when none exists — `domain.py:338-342`
- §3.4 rescission — insert — ambiguity — premature `ISSUANCE_DEADLINE_MISSED` → `ERR_INVALID_ASSIGNMENT_STATE` 409 — `assignments.py:125-132`
- §3.5 claim intake — insert — ambiguity — `expiration_date` is not an upper bound and `policy_status` is not tested — `claims.py:35-36`
- §3.5 closure — insert — ambiguity — `paid_cents` optional, defaults 0, non-negative; missing `denial_reason` → `ERR_INVALID_REQUEST` 422; `paid_cents` forced to 0 on `DENIED` — `claims.py:111-130`
- §3.5 clean years — insert — ambiguity — a future chargeable event credits 0, not a negative — `calc.py:209-213`
- §3.6 docketing — insert — ambiguity — the policy's `policy_status` is not tested — `complaints.py:33-37`
- §3.6 further review — insert — ambiguity — `disposition` and `resolved_by_user_id` are retained across the round trip — `complaints.py:124-133`
- §3.7 reclassification — insert — ambiguity — `reclassification_effective_date` is validated but neither stored nor used as the rating date — `policies.py:164`, `176`
- §3.7 non-renewal — insert — ambiguity — both the `IN_FORCE` and `non_renewal_notice_count == 0` failures report `ERR_INVALID_POLICY_STATE` 409 — `policies.py:267-268`
- §3.7 settlement — insert — ambiguity — `additional_premium_due_cents` is zeroed at cancellation — `policies.py:243`
- §3.7 exit credit — insert — ambiguity — period picked by the §2.10 rule; credit is 1.0 when no period exists — `policies.py:314-320`
- §3.8 exit notice — insert — ambiguity — exactly 90 days out is accepted (strict boundary) — `carriers.py:97`
- §3.8 cascade — insert — ambiguity — an empty receiver pool creates no successor, consumes no `batch_sequence`, and leaves the policy in `REASSIGNMENT_PENDING` — `carriers.py:118-124`
- §3.9 reconciliation — insert — ambiguity — `POLICY_COUNT` variance is 1 dp; obligation is the *live* §2.10 target, not the frozen period total; credited car-years are live against the clock while the obligation total is frozen — `reconciliations.py:20-42`, `domain.py:753-761`
- §5 intro — insert — ambiguity — `ERR_NOT_FOUND` 404 / `ERR_METHOD_NOT_ALLOWED` 405 for unrouted requests — `app.py:73-85`

Key findings worth flagging: the five mismatches are all genuinely observable — the certification gate order and the acceptance suspension/window order both contradicted the previous prose, `required_deposit_cents` recomputation was under-listed, policy issuance evaluated overlap before the licensing check (the reverse of the old narrative), and non-renewal maturation/`EXIT_COMPLETE` triggering was narrower in code than the PRD implied.

**Orchestrator verification:** `PRD_COMPLETED.md` is 441 lines / 103,989 bytes with the same 30 headings as `PRD_FINALIZED.md`; `diff` shows exactly 32 lines changed in place with no additions or deletions; the file ends on the final complete §5 error-table row (`| \`ERR_DEPOSIT_AMOUNT_INVALID\` | 422 |`), a real section boundary. Pipeline complete — all nine steps done.
