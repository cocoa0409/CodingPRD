# Worklog — task_2394_beverage_container_deposit_redemption_center

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2394_beverage_container_deposit_redemption_center/` and `workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T00:05:00.000Z

All three artifacts are complete and the lint is clean. Final verdict block, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2394_beverage_container_deposit_redemption_center/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2394_beverage_container_deposit_redemption_center/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2394_beverage_container_deposit_redemption_center/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     13
  §1.8 instances scanned:     22
  §1.9 instances scanned:     77
  Calls scanned (§1.8+§1.9):  1156

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Counts

- **§1.1–§1.7**: 13 entities, 10 state machines (12 dimensions — RedemptionVisit carries parallel `count_status`/`payout_status`), 3 OCC concurrency rules, 10 calculations, 39 ordered validations, 49 endpoints, 64 errors, 6 roles. `api_prefix: ""`, entity topology `flat`, role model `peer_roles`, consistency `immediate`.
- **§1.8**: all 9 required rule ids, 22 instances (dual_variant_calc 3, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2).
- **§1.9**: 88 instances across all nine guide sections — entities 12, state_machines 15, calculations 10, validations 8, endpoints 5, errors 23, rbac 7, cross_cutting_complexity_layers 7, consistency_model 1. 77 carry full `test_recipe`s; 11 are `excluded_because` stubs that each cite an existing §1.8 instance name (no stub carries a `test_recipe`).
- Verified independently: every one of the 64 error codes is triggered or stub-attributed; no duplicate §1.9 names; no forbidden concurrency vocabulary; all instances carry `claim_type`/`grounds`/`distinguishing_aspect` plus the four `test_recipe` keys.

## Design adjudications

1. **Two §1.4/§1.6 gaps closed rather than corners weakened** (per the §1.5 priority ladder): (a) validation priority 16 + `ERR_INVALID_MACHINE_STATE` were broadened to cover the `BIN_FULL` counter precondition (`bin_filled_count >= bin_capacity_containers`), which previously had no error; (b) validation priority 14 now reads `ERR_INVALID_PAYOUT_STATE | ERR_MANUAL_RECOUNT_REQUIRED` with the recount arm checked after the state arm, so the catalogued `ERR_MANUAL_RECOUNT_REQUIRED` finally has an ordered §1.4 home (it was only reachable through a §1.2 precondition).
2. Earlier adjudications retained: a priority-20 state validation with `ERR_INVALID_CENTER_STATE`/`ERR_INVALID_ACCOUNT_STATE`/`ERR_INVALID_OBLIGATION_STATE` (priorities renumbered 20→39); the untriggerable `ERR_PERIOD_NOT_RECONCILED` and its precondition removed; MaterialSale merged into CommodityBatch; the two immutable ledger entities keep polymorphic `source_kind`/`source_ref_id` deliberately outside FK reverse-reachability; OCC limited to the three write endpoints in §1.2.1; `ReverseVendingMachine.current_visit_id` replaced by `open_session_count`.
3. Hardness levers: a three-way minimum waterfall payout (visit limit × daily allowance × raw accepted) with channel-specific ceil shrink, pinned-order coverage clauses, PROVISIONAL/FINAL bag-drop variants reconciled by delta only, SPOT/INDEX per-bale rounding, event-replay liability projection, half-open 5-minute machine cooldown, closed-interval period overlap, inclusive 3.50-mile exemption boundary, and compensating REVERSE/VOID paths that must return every derived counter to its pre-event value.
4. The hard constraint held: no sibling `tasks/task_*/` directory was listed, read, or grepped; everything derives from the verbatim scenario plus the scaffold-generator skill and its claim-extraction guide.

## Step 3: Copy shared files — 2026-09-02T00:06:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T00:26:00.000Z

PRD generated at `workspace/PRD.md` (495 lines, ~14,250 words). Both withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced, and no sibling task directory was read.

## Section counts

| Section | Content |
|---|---|
| §1 Introduction | 3 paragraphs (user pain → business context → two design commitments) |
| §2 Global Specifications | 10 subsections: 2.1 RBAC · 2.2 Response Structure (byte-verbatim) · 2.3 Pagination · 2.4 Identity/Timestamps/Logical Clock · 2.5 Validation Precedence · 2.6 Stale-Version Guards · 2.7 Counts, Cents & Rounding · 2.8 The Two Journals & Liability Projection · 2.9 Derived Counters & Cascades · 2.10 Nested Path Resolution |
| §3 Business Logic | 9 subsections: 3.1 Distributors & label registration · 3.2 Centres, machines, retailer obligation · 3.3 Accounts, standing, credit journal · 3.4 Visits & lot screening · 3.5 Close-count valuation · 3.6 Payout dimension · 3.7 Bag-drop programme · 3.8 Commodity batches & material revenue · 3.9 Quarters & funding settlement |
| §4 Endpoint Definitions | 49 rows, 4 columns (Method, Path, Description, Authorized Role(s)) |
| §5 Error Code Catalogue | 64 rows, 2 columns (Error ID, HTTP Status Code) — file ends here, no audit footer |

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 149 required, 149 present, 0 missing
- endpoints[].request_body: 72 required, 72 present, 0 missing
- endpoints[].query_params: (included in the 72 above), 0 missing
Status: PASS
```
(required union incl. the 3 `occ_field` names = 160 identifiers, all present verbatim in backticks)

```
Rule coverage check:
- validations[] with priority: 39 checked, 39 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 56 checked, 56 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 39 checked, 39 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 26 checked, 26 expressed, 0 missing
- entities[].fields[] structured content: 149 checked, 149 reconstructible from prose, 0 missing
- sibling-branch symmetry: 12 groups checked, 12 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1135
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All 64 error IDs are raised in §1–§4 prose (46 in §3; the remaining 18 — auth, the ten not-found codes, invalid-request, pagination and the three OCC codes — are cross-cutting and live in §2.1/2.3/2.5/2.6/2.10). No pseudocode operators (`==`, `min(`, `ceil(`, `>=`, `->`) and no fuzzy words survive outside the verbatim §2.2 block.

## Zero-silence adjudications

1. **Scaffold header vs body counts.** The scaffold banner claims "62 error codes" and "38 ordered validations"; the body contains **64 errors** and **39 validations**. The body was treated as authoritative — §5 has 64 rows and §2.5 enumerates 39 numbered rungs.
2. **Paths in §2.5.** Contract 3 polices §3 only, so full URL paths are used inside §2.5 to make every validation's `applies_to` scope exact, while §3 stays strictly path-free and refers to operations by name.
3. **§3 subsection budget.** Retailer obligation/exemption was folded into §3.2 (rather than a 10th subsection) to stay inside the 5–9 guidance; it is also the natural home, since the exemption depends on `OPERATIONAL` centres.
4. **Action literals.** Action/event enum values are named both in §2.1's action-narrowing paragraph and in the §3 subsection that owns each state machine (`SORT`, `BALE`, `RECONCILE`, `REOPEN`, `CLOSE`, `FLAG`, `UNFLAG`, `ACTIVATE`, `SUSPEND`, `REINSTATE` were added to §3 during the audit, having previously appeared only in §2.1).
5. **Anonymous daily allowance.** The scaffold sets `daily_allowance = raw_accepted_count` for anonymous visits (commented "unconstrained"). Rendered literally as "treated as equal to `raw_accepted_count`, leaving it non-binding" rather than as "unlimited", so the reader can derive that the `DAILY_CAP_EXCEEDED` trigger can never fire on an anonymous visit.
6. **Clock endpoint.** `POST /_clock/set_current_utc` appears in the §4 table; its semantics (default `2026-08-01T00:00:00Z`, `to_iso8601`, never falling back to wall clock) are carried in §2.4 so no path is needed in §3.
7. **Boundary polarity stated explicitly everywhere it differs**: strict `>` for `out_of_state_ratio` and `|variance_pct|` at 0.1; non-strict for `cap_reached_today`, the 3.50-mile radius, `funding_status` at zero, and `bin_filled_count` vs `bin_capacity_containers`; half-open `[start, start+5min)` cool-down; strict `<` for the 72-hour dispute deadline.

## Step 5: Generate unit tests — 2026-09-02T02:03:00.000Z

Suite complete. Final state of task 2394:

## Files

`test_helpers/` (Stage 1, 9 files, 2 341 lines): `__init__.py` (barrel), `constants.py`, `types.py`, `api_errors.py` (64-member `ApiErrorId` + HTTP status map registered with the framework), `test_users.py` (6 roles, header builders), `api_client.py` (49 endpoints), `factories.py`, `assertions.py`, `fixtures.py`.

`test_suite/` (Stage 2, `conftest.py` + 17 test modules, 7 687 lines):
- Queue A: `test_01`…`test_07` — 44 tests
- Queue B: `test_08` entities (12), `test_09`/`test_10` state machines (18), `test_11` calculations (9), `test_12` validations (8), `test_13` endpoints + consistency (5), `test_14`/`test_15` errors (16), `test_16` rbac (7), `test_17` cross-cutting (5) — 80 tests

**124 tests collected**, pyflakes clean on every file, no `skip`/`xfail`, no mention of the scaffold anywhere.

## Coverage audit (both mandatory passes green)

- **Design pass**: every test has exactly one `Design:` line and it is the last docstring line; 99 distinct tags = **22/22 Difficulty instances** (0 stubs) and **77/77 non-stub Corner instances**. No tag points at a stub, an unknown name, or a wrong section. Per-corner-section: entities 12, state_machines 18, calculations 9, validations 8, endpoints 4, errors 16, rbac 7, cross_cutting 5, consistency_model 1.
- **PRD pass**: **202 `PRD:` quotes, 0 missing** — each is a whitespace-normalised literal substring of `workspace/PRD.md`, full sentences, rule-bearing (no endpoint titles, no ellipses).

## Skipped / adjusted

11 Corner stubs skipped (each carries its own `excluded_because` pointing at the §1.8 instance that already covers it): `calculations/handling_fee_marginal_tier_crossing_at_fifty_thousand_containers`, `endpoints/close_count_conditional_action_on_a_visit_with_no_lots`, `errors/{machine_session_inside_the_cooldown_is_refused, overlapping_program_period_is_refused, daily_cap_exhaustion_is_refused, non_operational_center_is_refused, exemption_distance_over_the_limit_is_refused, flagged_account_credit_is_refused, bag_drop_for_an_unenrolled_account_is_refused}`, `cross_cutting/{fourth_jam_cascade_reaches_the_center, spot_and_index_pricing_produce_different_net_revenue}`.

Individual design asserts dropped or corrected because the PRD does not uniquely derive them (instance itself still covered): two "extra field ignored" halves in entities; a `redemption_day` assert in `test_11`; two `version` asserts in `test_10` replaced with the PRD-derived values; `bale_count`/`gross_weight_kg` on a *refused* BALE replaced with a version-unchanged assert (`test_15`); the corner yaml's `variance_pct == 0.0500` for a 95-of-100 recount corrected to `-0.05`, which is what §3.7's signed formula gives (`test_17`); and CenterOperator→ProgramAdmin header substitutions on `RedeemerAccount` endpoints (`test_13`, `test_15`), since §2.1 gives CenterOperator no ownership path to an account.

## Step 6: Generate implementation — 2026-09-02T02:03:00.000Z

The implementation is complete and validated end-to-end.

## Files (25) — all under `workspace/implementation/`

`start.sh`, `requirements.txt`, `app.py`, `clock.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `validation.py`, `calculations.py`, `services/{__init__,projections}.py`, `routes/{__init__,common,distributors,products,centers,machines,visits,accounts,bag_drops,batches,retailers,periods,clock_routes}.py`

## Coverage

- **49 endpoints** registered — an exact one-to-one match with the PRD §6 table (verified by diffing the registered Flask rules against the table, including `/reverse-vending-machines/{id}` and `/reverse-vending-machines/{id}/machine-events`).
- 13 entities, 12 state dimensions, all 10 pinned calculations, 3 OCC rules, and the full 64-code error catalogue with statuses cross-checked line-by-line against PRD §5.

## Notable design decisions

- **Storage is in-memory only.** 13 plain dicts in `db.py`; a persistence audit (`grep` for `sqlite3`, `open(`, `json.dump`, `pickle`, `shelve`) returns nothing, and no file appears in the directory after a full run. A fresh boot returns `total_count: 0` on every list endpoint and a logical clock of exactly `2026-08-01T00:00:00.000Z`.
- **Hidden monotonic `_seq`** on every record gives a stable total order under a frozen clock, so `created_at ASC` listing, the payout waterfall and the ledger replay are deterministic. `_`-prefixed keys are stripped on serialization.
- **`touch()` is idempotent per HTTP request** (tracked in `flask.g`), so a request that recomputes several derived counters and replays a projection still bumps `version` by exactly 1 — confirmed: RECONCILE = +1, REOPEN = +1.
- **Liability is a replay projection**, never an accumulator; each replay rewrites every line's `liability_after_cents`.
- `start.sh` guards `pip install` behind an `import flask` probe so per-test reboots (and the concurrent stability sweep) do not thrash pip.
- One spec contradiction resolved in favour of PRD §3.6: the cash drawer is maintained incrementally (`PAY -=`, `REVERSE +=`), which returns 50000 after reversing a 2200 payout from a 50000 drawer, rather than §2.9's literal formula (which would yield 52200).

## Verification

Three HTTP smoke suites (~150 assertions) were run against freshly booted servers and **all pass**. Every initial mismatch turned out to be a wrong expectation in my scratch test, each re-verified against the PRD: `out_of_state_ratio` denominator is `presented_total`; `PAID_PARTIAL` (not `PARTIAL_PAID`); the centre's own `daily_account_cap_containers` (default 350) is the daily cap, not the visit ceiling; `funding_balance` subtracts `operating_cost`; `daily_limit_containers` is 50/24 at the 5000 sqft line; installing a machine bumps the centre's `version`; rung 21 does not gate payout actions; `ERR_ACCOUNT_BALANCE_NONZERO` and `ERR_CONTAMINATION_LIMIT_EXCEEDED` are 409/422 respectively; the DISPUTE narrowing is one-directional (a `CenterOperator` may dispute).

Verified behaviours include: the 5-stage close-count valuation at all three ceilings (240/50/retailer, with the 144 anonymity narrowing), the 2% ROUND_CEILING hand-count shrink, both fraud triggers with the 2-strike `ACCOUNT_FLAGGED` overwrite, `ERR_DAILY_CAP_EXHAUSTED`, the full 4-jam machine cascade with the 5-minute half-open cooldown window and the `MACHINE_FLEET_DOWN` centre suspension, per-bale-rounded SPOT and INDEX material sales (6355/193/6162 and 6194/185/6009), bag-drop provisional → count → dispute → recount → credit/void with the strict 72-hour window boundary, the retailer exemption distance rule, the centre-closure cascade (machines retired, exemptions cleared), and RECONCILE/REOPEN/CLOSE with compensating ledger lines.

Server boots cleanly from `start.sh` on every invocation; all test servers I launched have been shut down.

One environment note: ~178 unrelated `python3 app.py` processes are currently alive on the host, spawned by the concurrently running test-generation sweep — I left those untouched, but they will make the host look loaded if you check.

## Step 7: Run tests and iterate — 2026-09-02T12:05:00.000Z

Resumed pipeline: filesystem inspection confirmed Steps 1-6 artifacts all satisfied (SCAFFOLD.yaml 3193L / SCAFFOLD_DIFFICULTY_DESIGN.yaml 1889L / SCAFFOLD_CORNER_DESIGN.yaml 5070L all non-empty; workspace/INSTRUCTION.md present; workspace/PRD.md complete at 494 lines with all 5 sections and a cleanly-terminated Error Code Catalogue table; test_suite/ with 17 test_*.py + test_helpers/ present; workspace/implementation/ with source + start.sh present). Steps 2-6 were therefore NOT re-run. Stale results.*.json from a prior partial sweep (which had been failing at 51-66 passed with inconsistent totals of 72-93, i.e. interrupted collection) were deleted before the first sweep.

Iterations run: 2 (each a full 8-round parallel sweep, `setsid nohup`, per-test-server isolation, 124 tests x 8 rounds = 992 test executions per sweep).

Sweep 1 — 7/8 rounds at 124/124. Round 7 had a single failure:
- `test_07_validation_precedence_pairs.py::TestCentreStateBeatsDailyCap::test_the_losing_cap_rule_was_genuinely_violated_too` -> `requests.exceptions.ConnectionError: ConnectionResetError(104)` raised inside `_read_status`, i.e. the server socket died mid-request. No assertion tripped.

Diagnosis (STEP 0) ruled this load-induced rather than a defect:
- The failure is transport-level, not an assertion; the endpoint under test (`POST /redemption-visits/{id}/lots`) has no timing logic.
- Its sibling test in the same class, sharing the identical `_suspended_centre_and_exhausted_holder` setup chain, passed in the same round — so the fixture/precondition chain is sound.
- The setsid-reaping signature was absent: server logs ended in `Killed` (the runner's own `kill -9`), never `Terminated`, and the rounds did not die at a common wall-clock instant.
- Host was at load average 40-76 with 105 GB free RAM, so CPU contention, not OOM; this test has one of the heaviest setup chains in the suite (~15 sequential HTTP calls: world build, two full counted visits, a third visit, a centre suspension).

Sweep 2 (confirmation) — 8/8 rounds at 124/124 passed, 0 failed, 0 errors, 0 skipped. The reset did not recur, confirming the load-induced read.

- Tests deleted: none. No test failed a PRD coverage or unique-derivability check — the one failure never reached an assertion.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `test_suite/`: none.
- Fixes applied to `implementation/`: none. The artifact was already correct; changing it would have been chasing a bug that does not exist.

Results for the clean sweep are at `workspace/implementation/results.1.json` ... `results.8.json` (all 124/124). `workspace/sweep.log` retains the final sweep's output.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T12:07:00.000Z

Skip condition satisfied. Step 7 reached a clean 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. The only failure observed across both sweeps was a transport-level `ConnectionResetError` attributable to host CPU contention, which was resolved by re-running the sweep and involved no artifact change.

Step 8's hard scope is bounded to `<step_7_diff>` items — the sites where a Step 7 fix, deletion, or assertion-weakening revealed PRD silence or PRD/implementation mismatch. With an empty diff there are no such sites, so there is nothing for Step 8 to patch, and `workspace/PRD_FINALIZED.md` is deliberately not produced. Editing PRD.md outside that scope would violate the skill's HARD SCOPE rule and risk introducing new mismatches for Step 9 to undo. Residual PRD silences that never produced a Step 7 failure signal are exactly what Step 9's full PRD-vs-implementation scan exists to close.

Decision made autonomously per the run's non-interactive mandate. Step 9 will therefore start from `workspace/PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T12:29:00.000Z

Source: `workspace/PRD.md` (Step 8 skipped, so no `PRD_FINALIZED.md` to start from) — 494 lines, 103,489 chars.
Output: `workspace/PRD_COMPLETED.md` — 494 lines, 115,428 chars. Char delta **+11,939**; line delta **0** (no new paragraphs, no new sections — 48 rewritten lines, all in-paragraph inserts/revisions). All 5 original sections preserved.

Counts: **29 ambiguity-pins** (PRD silent -> minimal inline prose), **17 mismatch-revisions** (PRD stated something `implementation/` contradicts).

Changes:
- §2.1 — insert — ambiguity — `own()` compares an entity-backed role only against identifiers of its own kind, and list endpoints are never narrowed to the principal — middleware.py:48
- §2.1 — insert — mismatch — action-level narrowing runs *after* the rung-4 ownership check and before the 404 and the action-enum match — visits.py:355, centers.py:78
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + 16 lower-case alphanumerics; `api_request_timestamp` reads the logical clock, not wall time — response.py:9
- §2.3 — insert — ambiguity — filters compare as exact strings; unrecognised query params ignored — routes/common.py:95
- §2.4 — revise — mismatch — `version` increments once per *request*, not once per mutation, however many effects hit the record — db.py:56
- §2.4 — insert — ambiguity — clock endpoint ignores `X-User-ID`, accepts no headers, `to_iso8601` parsing rules, answers 200 with `{}` — clock_routes.py:12
- §2.5 preamble — insert — ambiguity — action-specific preconditions are tested immediately after their own state rung — centers.py:93
- §2.5 rungs 2-3 — revise — mismatch — on the clock endpoint the role checks bite only on a role that was actually supplied — clock_routes.py:16
- §2.5 rung 6 — insert — ambiguity — fixed per-endpoint FK resolution order, before rung-7 pairing; non-string keys are rung-7 failures — visits.py:35, bag_drops.py:35
- §2.5 rung 11 — revise — mismatch — "six operations" corrected to **seven** (the enumeration already listed seven, and all seven are gated) — visits.py:255, batches.py:31
- §2.5 rung 12 — insert — ambiguity — closing the count of a `RETAILER` visit does not re-check obligation — visits.py:255
- §2.5 rung 21 — revise — ambiguity — exactly which operations consult standing; `FLAGGED` blocks only `CREDIT`; `DISPUTE`/`VOID` test only `CLOSED` — bag_drops.py:146
- §2.7 — insert — mismatch — the 2-decimal-place rule on `bale_weights_kg` is *not* enforced; only positivity is — validation.py:148, batches.py:91
- §2.8 — insert — ambiguity — `memo` is always present and null on every server-written line — projections.py:24
- §2.8 — insert — ambiguity — the single replay also restates steps 1-3 roll-ups and leaves steps 4-10 untouched — projections.py:47
- §2.9 — insert — mismatch — the drawer reads 0 while `PROVISIONAL` and `RETAILER` payouts never move any drawer — centers.py:96, visits.py:418
- §2.9 — insert — mismatch — a cascade bumps `version` once for the whole request even when several effects land on one record — db.py:56
- §3.1 — revise — mismatch — `upc` is a non-empty string whose digit count is never policed; coverage fields null on creation — products.py:41
- §3.1 — insert — ambiguity — `SUBMIT`/`WITHDRAW` are not narrowed to `DistributorAgent`; withdrawal leaves the coverage fields as they stood — products.py:16
- §3.1 — insert — ambiguity — deposit initiation answers 201 with the new `DepositLedgerEntry`; the listing spans all quarters and takes no filter — distributors.py:72
- §3.2 — revise — ambiguity — coordinates are any JSON numbers, `accepted_materials` may be empty, cap/opening-cash minimum 0, `accepts_all_materials` never cross-checked — centers.py:30
- §3.2 — insert — ambiguity — after a close cascade both machine counters read 0; only still-`EXEMPT` stores are released — projections.py:179
- §3.2 — revise — ambiguity — `bin_capacity_containers` minimum 1, install allowed in any centre status, full initial machine field set — centers.py:117
- §3.2 — revise — ambiguity — `visit_id` mandatory on `SESSION_OPEN` (`ERR_INVALID_REQUEST` after state+cool-down); the machine privately remembers its occupying visit — machines.py:92
- §3.2 — revise — mismatch — cool-down is tested *before* the coherence checks; a correctly paired visit in `JAM_HOLD`/`COUNTED` gives `ERR_INVALID_COUNT_STATE` — machines.py:88
- §3.2 — revise — mismatch — the jam cascade only moves `COUNTING -> JAM_HOLD` but always sets the flag and counter — machines.py:151
- §3.3 — revise — ambiguity — full initial account field set (`containers_redeemed_today`, `cap_reached_today`, `redemption_day`, `last_strike_reason`) — accounts.py:37
- §3.3 — revise — ambiguity — `amount_cents` is an integer >= 0 (zero accepted); the call answers 201 with the new `AccountCreditEntry` — accounts.py:68
- §3.4 — insert — ambiguity — full initial visit field set (all roll-ups 0, flags false, three timestamps null) — visits.py:72
- §3.4 — revise — mismatch — account standing is tested *before* machine/centre coherence — visits.py:62
- §3.4 — revise — mismatch — lot guards run operational/obligated first, then `count_status`, then registration and material; no material test on a `RETAILER` visit — visits.py:162
- §3.4 — insert — ambiguity — lot addition answers 201 with the created `ContainerLot` — visits.py:225
- §3.5 — insert — ambiguity — an anonymous visit takes the out-of-state hold with no strike; both triggers firing records two strikes and lands on `DAILY_CAP_EXCEEDED` — visits.py:311
- §3.6 — revise — mismatch — an explicit `WITHHOLD` never raises `fraud_hold`; `RELEASE_HOLD` refuses with `ERR_ACCOUNT_CLOSED`/`ERR_ACCOUNT_FLAGGED` — visits.py:384
- §3.6 — insert — ambiguity — `REVERSE` resolves the quarter exactly as `PAY` does; bucket rollback only on a matching `redemption_day`, floored at 0 — visits.py:407
- §3.7 — insert — ambiguity — full initial bag field set — bag_drops.py:54
- §3.7 — revise — ambiguity — `counted_quantities` must hold at least one element, each an integer >= 0 — bag_drops.py:102
- §3.7 — insert — mismatch — a `CREDIT` against a `RECONCILING`/`CLOSED` containing quarter reports `ERR_NO_OPEN_PERIOD`, not `ERR_INVALID_PERIOD_STATE` — bag_drops.py:172
- §3.8 — insert — ambiguity — full initial batch field set — batches.py:38
- §3.8 — revise — mismatch — `contamination_pct` is *optional* on `SORT` and stored as 0 when omitted — batches.py:89
- §3.8 — revise — ambiguity — `quoted_price_cents_per_tonne` integer >= 0; batch state tested before period state — batches.py:125
- §3.9 — revise — ambiguity — `operating_cost_cents` is an integer >= 0 — periods.py:31
- §3.9 — revise — mismatch — the bag-drop `CREDIT` is excluded from the blanket "non-`OPEN` quarter => `ERR_INVALID_PERIOD_STATE`" rule — bag_drops.py:175
- §4 — revise — mismatch — deposit initiation, credit action and lot addition all answer **201** with the appended row; clock returns an empty object — distributors.py:72, accounts.py:89, visits.py:225
- §4 table — revise — ambiguity — clock row: 200 with `{}`, headers optional, supplied role must be a recognised `ProgramAdmin` — clock_routes.py:13
- §5 — insert — ambiguity — `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) exist outside the workflow catalogue; unparseable bodies are `ERR_INVALID_REQUEST` — app.py:27

Findings worth flagging upstream to the doc-generator: PRD §2.5 rung 11 was internally inconsistent ("six operations" while enumerating seven — the implementation gates all seven), and three action endpoints break the PRD's blanket "action endpoints return 200 with the updated resource" rule by returning 201 with the newly appended journal row.

Pipeline complete.
