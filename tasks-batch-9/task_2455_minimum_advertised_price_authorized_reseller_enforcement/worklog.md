# Worklog — task_2455_minimum_advertised_price_authorized_reseller_enforcement

## Step 1: Create task directory — 2026-09-02T20:04:46.468Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2455_minimum_advertised_price_authorized_reseller_enforcement` and its `workspace/` subdirectory. Index 2455 was pre-assigned by the invoking pipeline; no index allocation scan was performed (other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-03T00:14:43.262Z

### Attempt 1 — first two spawns died on API errors, third timed out after 75 minutes

The Step 2 scaffold subagent was spawned three times. The first two returned `API Error: The system encountered an unexpected error during processing` before doing any work. The third ran for 4,503 s (~75 min) and was killed by a server-side request timeout, but had already written all three output files to disk before dying.

### Orchestrator triage of the timed-out attempt

Orchestrator-run verification found two defects in the recovered artifacts.

**Defect 1 — SCAFFOLD.yaml did not parse.** 25 `input:` flow sequences contained bare `?`-suffixed optional field names (e.g. `input: [policy_code, shipping_counts_as_advertised?, ...]`). PyYAML terminates a plain scalar at `?` in flow context and then reads the `?` as a complex-mapping-key indicator, so the file raised `ParserError ... expected ',' or ']', but got '?'` at line 1838. Fixed mechanically by quoting only the `?`-bearing elements on those 25 lines (`"shipping_counts_as_advertised?"`). This is a pure serialization fix — no field name, endpoint, or design decision was altered. SCAFFOLD.yaml then parsed clean: 12 entities, 61 endpoints, 16 state machines, 15 calculations, 21 validations, `complexity_profile.difficulty_level: expert_plus`, and neither forbidden `scaffold_difficulty_design` nor `scaffold_corner_design` key present.

**Defect 2 — the two design indices were written against a superseded SCAFFOLD.yaml.** File mtimes tell the story: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` 21:25, `SCAFFOLD_CORNER_DESIGN.yaml` 22:16, `SCAFFOLD.yaml` 22:55. The subagent rewrote the endpoint table *after* generating both design indices and was killed before reconciling them. `scaffold_lint.py` over the task directory reported **1967 violations** across 1117 scanned calls — 508 calls to endpoints not declared in §1.5, 526 role/endpoint RBAC mismatches, 418 undeclared payload keys, 388 missing required input fields, 127 unresolvable capture JSONPaths. Violations were spread over every single §1.8 rule and every §1.9 section, so this was not a patchable edge — the indices simply target a different API surface than the one the scaffold now declares.

### Adjudication (decided by the orchestrator; no user is available to consult)

Rather than re-run the whole of Step 2 — which had already burned 75 minutes and timed out once, and would discard a coherent scaffold — the orchestrator **froze SCAFFOLD.yaml as authoritative and regenerated only the two design indices against it**. Rationale: SCAFFOLD.yaml is the newest artifact and therefore represents the generator's final design intent; it is internally consistent; and it lints clean on its own (verified by running `scaffold_lint.py` against a scratch directory holding the frozen SCAFFOLD.yaml plus empty `[]` design stubs → `VERDICT: clean lint`). The §1.8/§1.9 indices are pure test-targeting projections *of* the scaffold, so regenerating them against the frozen scaffold is precisely the correct repair, and it is strictly cheaper and lower-risk than regenerating all three.

The stale indices were quarantined to `/tmp/s2455_diff/STALE_DIFFICULTY.yaml` and `/tmp/s2455_corner/STALE_CORNER.yaml` (kept readable to the regeneration agents as a source of domain-specific worked numbers, but explicitly flagged as misaligned and not to be copied wholesale).

### Difficulty-instruction containment

The pipeline invocation required that the line `Generate task harder than expert level!` reach the scaffold generator only, and never leak into PRD.md. The scaffold generator had embedded it verbatim as the first line of SCAFFOLD.yaml's `scenario:` block — and Step 4's doc generator reads SCAFFOLD.yaml. The orchestrator therefore **stripped that line (and its blank line) from the `scenario:` block** so the leak cannot occur. The instruction's effect is preserved downstream by `complexity_profile.difficulty_level: expert_plus`, which the scaffold generator had already recorded. The `scenario:` block now begins at `2455. Minimum Advertised Price & Authorized Reseller Enforcement ...` with the rest of the scenario text intact and unmodified.

### Regeneration launched

Two agents regenerate §1.8 and §1.9 concurrently, each in its own scratch directory (`/tmp/s2455_diff`, `/tmp/s2455_corner`) holding a copy of the frozen SCAFFOLD.yaml plus an empty stub for the *other* index — so each can run `scaffold_lint.py` in isolation without racing the other's partial writes. Each agent is under a hard gate: iterate until `scaffold_lint.py` reports zero violations attributable to its own section, then and only then copy its file into the real task directory. Both were told SCAFFOLD.yaml is read-only, warned about the `?`-in-flow-sequence YAML trap, and told to batch their writes (the previous run's death was partly attributable to building 170 KB and 319 KB files through many small edits).

## Step 3: Copy shared files — 2026-09-03T00:14:43.262Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).


## Step 4: Generate PRD — 2026-09-03T00:28:00.000Z

Launched concurrently with the Step 2 design-index regeneration. This is safe and deliberate: the doc generator reads **only** `SCAFFOLD.yaml`, which the orchestrator had already frozen, and it is forbidden from reading either design index — so it has no data dependency on the two agents still running. The subagent confirmed it never opened either design file (they did not exist in the directory while it ran).

### Orchestrator-run truncation check (the known doc-generator failure mode)

`PRD.md` is 453 lines / 102,178 bytes. Section headings walk cleanly `# title → §1 Introduction → §2.1–§2.11 → §3.1–§3.9 → §4 Endpoint Definitions → §5 Error Code Catalogue`, and the file's final line is a complete `| ERR_OVERRIDE_FLOOR_OUT_OF_RANGE | 422 |` table row — a real section boundary, not a mid-sentence cut. §4 contains exactly 61 endpoint rows (matching the scaffold's 61 endpoints) and §5 exactly 52 error rows. **Not truncated; no regeneration needed.**

### Orchestrator-run difficulty-instruction leak check

`grep -in 'harder than expert|expert level|expert_plus|SCAFFOLD|difficulty_design|corner_design|test_recipe' PRD.md` → **no matches**. The Step 2 strip of the `scenario:` block held; the difficulty directive did not reach PRD.md.

### Subagent summary (verbatim)

PRD generated at `.../workspace/PRD.md` — 454 lines, 102 KB. `SCAFFOLD.yaml` untouched (mtime/size unchanged). `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened (they do not yet exist in the directory).

Section list: 1. Introduction (3 paragraphs). 2. Global Specifications — 2.1 Channel Actors and RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination and List Ordering · 2.4 Record Identity, Timestamps and Revision Counters · 2.5 Money, Points and Rounding Discipline · 2.6 The Deterministic Logical Clock · 2.7 Antitrust Guardrails on Unilateral Process · 2.8 Optimistic Concurrency on the Two Ledgers · 2.9 The Order in Which a Request Is Rejected · 2.10 Flat Addressing and Reference Discovery · 2.11 Reconciliation Invariants on Derived Aggregates. 3. Business Logic — 3.1 Policy drafting/review/publication · 3.2 Product catalogue and standard floors · 3.3 Distributors, reseller applications, the two reseller axes · 3.4 The authorized reseller agreement · 3.5 Evidence capture and advertised-price evaluation · 3.6 Clearance/bundle/promotional exceptions · 3.7 The enforcement ladder · 3.8 Serialized tracing and test purchases · 3.9 Distributor accountability, diversion exposure, the sweep. 4. Endpoint Definitions (4 columns). 5. Error Code Catalogue (2 columns).

Coverage vs. scaffold (mechanically verified):

```
Field coverage check:
- entities[].fields:            128 required, 128 present, 0 missing
- endpoints[].request_body:      86 required,  86 present, 0 missing
- endpoints[].query_params:      33 required,  33 present, 0 missing
- endpoints[].path_params:       12 required,  12 present, 0 missing
- computed-read output ids:      39 required,  39 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority:   13 checked, 13 expressed as an explicit 1→13 ordered ladder in §2.9, 0 missing
- concurrency_rules[] OCC:        2 checked,  2 expressed (write_endpoint + expected_reseller_version /
                                  expected_distributor_version + ERR_STALE_*_VERSION + 412), 0 missing
- state_machines[].transitions:  46 checked (10 machines), 46 fully expressed, 0 missing
- calculations[]:                13 checked (incl. 4 named variants), 13 fully expressed, 0 missing
- validations[] conditions:      13 checked, all matchable to their error_ids in prose, 0 missing
- endpoints[].side_effects:      63 items over 34 endpoints, all expressed in §3, 0 missing
- entities[].fields[] structure: 128 checked (types, defaults, initial values, enum sets), 0 missing
- sibling-branch symmetry:        8 groups (policy review fork, agreement respond fork, evaluate
                                  compliant/breach fork + matched/unmatched sub-fork, exception decision
                                  fork, violation dispute-decision fork, chargeback dispute-decision fork,
                                  exposure variants, points variants) — equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1040
- tokens starting with `/`: 0 · bare HTTP-method tokens: 0 · method+path tokens: 0
Status: PASS
```

§4 has exactly 61 rows (matches the 61 scaffold endpoints); §5 has exactly 52 rows. All 52 real `ERR_*` ids in the scaffold appear in §2/§3 prose and in the §5 table — no invented codes. No fuzzy/approximating words (the four "about" hits are all the preposition).

Two things worth flagging to the pipeline:

1. **The scaffold has no `errors:` (§1.6) or `roles:` (§1.7) block.** It ends at the clock endpoint. I derived the role set from validation priority 1 ("one of the six declared roles") plus `endpoints[].roles`, and the identity model from validation priority 6 (`Reseller` and `Distributor` entity-backed, the four brand/platform roles opaque). I derived the 52-code catalogue from the error ids named across `validations`, `state_machines`, `calculations` and `concurrency_rules`, and pinned a single HTTP status for each code whose validation row declared a range (`409 | 422`, `403 | 409 | 422`). Those status assignments are my choice, not the scaffold's — the unit-test generator should read them from the PRD, not re-derive them.

2. **Four internal scaffold conflicts** where the §1.2 state-machine trigger and the §1.5 endpoint `side_effects` disagree. I followed §1.2 in all four, since it is the more specific table and is corroborated elsewhere: policy review `decision` is `APPROVE_FOR_PUBLICATION` / `RETURN_FOR_REVISION` (not `APPROVE`/`RETURN`); violation dispute `decision` is `REJECT` / `SUSTAIN` (not `UPHOLD`/`REVERSE` — corroborated by the `DISPUTE_SUSTAINED` literal); test-purchase `outcome` is `UNAUTHORIZED` / `AUTHORIZED` (not `CONFIRM`/`CLEAR`); notice rescission returns the cited violation to `DETECTED` (not `VOIDED`). Separately, §1.5 says curing removes points from the ledger while §1.2 and `calculations.reseller_points_ledger` both retain them — I specified retention, since `CURED` is in `LEDGER_STATUSES`.

### Orchestrator note on flag (2)

The four §1.2-vs-§1.5 conflicts are a genuine scaffold defect, inherited from the timed-out Step 2 run. The doc generator resolved all four toward §1.2 with stated corroboration, which is the defensible reading. Because the benchmark contract is *PRD is the contract*, the PRD's resolution is now authoritative for Steps 5/6/7 regardless of what the scaffold says — the implementer never reads the scaffold. The §1.9 regeneration agent works from the scaffold, so a handful of §1.9 instances may encode the §1.5 spelling of these four enums; if that surfaces in Step 7 it will be adjudicated there under STEP 1a (PRD silence → delete) rather than by editing the PRD.

## Step 2 (continued): design-index regeneration completed — 2026-09-03T01:24:00.000Z

Both regeneration agents finished and copied their files in. **Orchestrator-run verification over the real task directory:**

```
  §1.5 endpoints declared:    61
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     355
  Calls scanned (§1.8+§1.9):  4807

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Down from 1967 violations to zero. `SCAFFOLD.yaml` is byte-identical to the frozen version (both agents confirmed they never wrote to it). Step 2 is now genuinely complete: `SCAFFOLD.yaml` 119,703 B · `SCAFFOLD_DIFFICULTY_DESIGN.yaml` 141,869 B · `SCAFFOLD_CORNER_DESIGN.yaml` 586,952 B.

### §1.8 subagent summary (verbatim)

§1.8 regenerated from scratch against the frozen scaffold and delivered.

**Final lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (18 §1.8 instances scanned, 336 calls, zero violations — clean on the first lint run; no scaffold file was touched.)

**Delivered:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (141,869 bytes, single top-level key `scaffold_difficulty_design`, 9 rules). Nothing else written to the task directory; `SCAFFOLD_CORNER_DESIGN.yaml` untouched.

**Coverage — 9 rule_ids × 2 instances = 18 total, all 18 non-stub (§1.8 has no stub concept; every instance has full `setup_api_calls`/`trigger`/`assert`):**

| rule_id | instances |
|---|---|
| dual_variant_calc | violation_points PROVISIONAL (6 pts, floor 10000) vs FINAL (3 pts, floor 8500 after a retroactive exception) · distributor exposure TRACE_ATTRIBUTED 2500 vs LOT_PRORATED 1500 (0.6 units) with the peer distributor at 0/1000 |
| combinatorial_formula | bundle allocation 3333/3333/3334 residual-to-last (mode b, nested rounding order) · chargeback tier from PRE-increment score, 2500 then 4000 (mode c, pinned evaluation order) |
| non_linear_state_machine | PricingPolicy DRAFT↔IN_LEGAL_REVIEW twice → revision_number 3, version 8 (cycle) · Reseller parallel axes: supply HOLD→OPEN→HOLD(AGREEMENT_EXPIRED) with authorization pinned AUTHORIZED |
| transitive_cascade | depth-4 TERMINATION: notice → Reseller → Agreement → SerialUnit RECALLED, + CLOSED_MOOT branch, ledger 23 · chargeback REVERSE → Distributor standing → Reseller.review_required |
| priority_pair_validation_conflict | p9 antitrust beats p10 ERR_POLICY_NOT_PUBLISHED (control call proves both live) · p8 ERR_STALE_DISTRIBUTOR_VERSION 412 beats p13 ERR_CHARGEBACK_CAP_EXCEEDED 402 |
| boundary_precision_check | advertised price exactly == floor (10000, deviation 0, empty violation set) vs 9999 → deviation_pct 0.0001 · cumulative points exactly == 6 threshold ⇒ SUSPENSION (inclusive lower bound) |
| cross_entity_state_dependency | Agreement COUNTERSIGNED→ACTIVE blocked by WITHDRAWN policy · SerialUnit ship-downstream gated by Reseller supply HOLD, then succeeds after release (version 1→2 proves the refusal was side-effect free) |
| resource_temporal_overlap | Product exception calendar: half-open adjacency OK, 1-second overlap rejected, channel-scope miss OK, scope ALL rejected · Reseller suspension calendar: CLOSED-interval touch rejected + 14-day cooling-off buffer, boundary 2026-09-08 accepted |
| compensating_invariant | rescission restores violation_points_total 14 → 6 == recomputed ledger sum, reinstates the reseller · chargeback UPHOLD moves nothing (18000/15.0), REVERSE of CB1 restores 8000/5.0 and re-derives GOOD while CB2 keeps its 4000 tier snapshot |

**Design adjudications** (recorded in the file header; the frozen scaffold states two spellings/behaviours in a few places and §1.5's request contract was taken as authoritative):
- `review-decision` → `APPROVE`/`RETURN`; `confirm-outcome` → `CONFIRM`/`CLEAR`; violation `dispute-decision` → `UPHOLD`/`REVERSE` (§1.2 used different verbs).
- Notice rescind puts the cited Violation in **VOIDED** (§1.5) not DETECTED (§1.2) — decided by §1.3 `reseller_points_ledger`, which explicitly pins VOIDED ⇔ `assessed_points == null`, and by the Violation machine having no NOTICED→DETECTED edge.
- Avoided the `policy_code` uniqueness-vs-supersede contradiction entirely: no instance publishes a second policy in the same lineage; supersession is exercised nowhere and cross-entity policy-state dependence uses WITHDRAW instead.
- `grounds:` reference only `calculations.*`, `state_machines.*`, `validations[priority=N]`, `entities.*.fields.*`, `concurrency_rules[*]` — the frozen scaffold has no §1.6 `errors:` or §1.7 `roles:` block, so error ids and roles are cited from §1.4 and endpoint `roles:` lists.
- Every instance is empty-DB reproducible: explicit `POST /_clock/set_current_utc` to 2026-08-01T00:00:00Z, `effective_from` == that instant, clock advanced to 2026-08-10 before observations so `observed_at` satisfies both the 30-day staleness window and `effective_from <= observed_at`; all OCC tokens are captured by a `GET` immediately before the mutation.

### §1.9 subagent summary (verbatim)

§1.9 corner design for task 2455 is regenerated, lints clean, and is in place.

`SCAFFOLD_CORNER_DESIGN.yaml` (587 KB, single top-level key `scaffold_corner_design`, 9 sections, 355 instances, 0 `excluded_because:` stubs — every instance is non-stub with a full `setup` / `setup_api_calls` / `trigger` / `assert` recipe). Nothing else was written into the task directory. `SCAFFOLD.yaml` is byte-identical (md5 `d9112b8a…`) in both `/tmp/s2455_corner` and the task dir; `SCAFFOLD_DIFFICULTY_DESIGN.yaml` in my workdir was never touched.

Lint verdict (verbatim, run against the task dir with the concurrent agent's real §1.8 present):

```
  §1.5 endpoints declared:    61
  §1.8 instances scanned:     18
  §1.9 instances scanned:     355
  Calls scanned (§1.8+§1.9):  4807

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Per-section instance counts (all non-stub):

| section | n | claim_type breakdown |
|---|---|---|
| entities | 40 | creation 12, computed_fields 4, not_found 4, required_fields 4, type_constraints 4, defaults 3, parent_relationships 3, retrieval 2, listing 2, system_fields 2 |
| state_machines | 87 | valid_transition 46 (one per declared transition), terminal_state_lockdown 10, invalid_transitions 10, precondition_enforcement 9, side_effect_execution 6, initial_state 3, idempotency 3 |
| calculations | 45 | correct_result 16, input_set_filtering 10, constants_applied 8, precision 6, variant_divergence 3, variant_selection 1, variant_reconciliation 1 — all 13 §1.3 calculations |
| validations | 69 | violation_to_error 53, priority_ordering 9, satisfaction_to_pass 7 — all 13 priorities |
| endpoints | 64 | standard_crud 31, action_endpoint 13, conditional_action 9, cross_reference_link 6, computed_read 3, bulk_action 2 |
| errors | 14 | violation_to_error 14 |
| rbac | 18 | cannot_perform_other_roles_exclusive_operations 8, can_perform_exclusive_operations 6, can_perform_shared_operations 2, segregation_of_duties 2 |
| cross_cutting_complexity_layers | 15 | optimistic_concurrency 4, rate_threshold_triggers 4, derived_field_reconciliation 4, cascading_side_effects 3 |
| consistency_model | 3 | immediate 3 |

Verified mechanically: all 61 declared §1.5 endpoints are exercised by at least one call; all 355 names unique and disjoint from the 18 §1.8 names; every error id appearing in any §1.4 `error_id` string is triggered somewhere in the file; every instance carries all five required keys and all four `test_recipe` keys.

Design adjudications for the sections completed this session:

1. **No standalone §1.6/§1.7 in the frozen scaffold.** Error ids live only inside `validations[].error_id` and roles only inside endpoint `roles:` lists, so `errors` grounds cite `"validations[priority=N].error_id.ERR_X"` and `rbac` grounds cite `"endpoints.<METHOD PATH>.roles"`.
2. **`errors` section scoped as the guide's cross-check**, not a re-derivation: codes already triggered by the `validations` section are not duplicated. What remained uncovered was the priority-4 path-existence family, so all twelve `*_NOT_FOUND` codes get one instance each on a distinct endpoint, plus two cross-checks of shared codes on untouched endpoint families (`ERR_VALIDATION` on `POST /distributors`, `ERR_INVALID_STATE` on the PricingPolicy machine).
3. **RBAC claim_type names derived verbatim from the guide's two Table-7 bullets** (`can_perform_exclusive_operations`, `can_perform_shared_operations`, `cannot_perform_other_roles_exclusive_operations`) plus the declared role-model row `segregation_of_duties` — no invented categories. The denial code asserted is the scaffold's actual `ERR_ROLE_NOT_PERMITTED`, not the guide's generic `ERR_UNAUTHORIZED`.
4. **SoD scope corrected against §1.4 p12 verbatim**: the rule binds only a TERMINATION notice to a different `X-User-ID` than the issuer of the *governing SUSPENSION*. So WARNING→SUSPENSION by the same `bcm-1` is legal; the negative instance needs the SUSPENSION issued by `counsel-1` and the TERMINATION attempted by `counsel-1`, with `counsel-2` as the positive counterpart.
5. **Threshold boundaries made exact by tuning policy knobs rather than hunting for convenient point totals.** `POST /pricing-policies` accepts the thresholds, so MAP-2026-E (suspension 7 / termination 12) makes the ladder land on 3 → 7 → 12 exactly: 14000 MARKETPLACE gives base 2 × 1.5 = 3, then ×1.25 repeat = 3.75 → 4, then ×1.50 = 4.5 → 5. MAP-2026-F (suspension 8) is the identical ledger one point below the bar and stays WARNING.
6. **Instantaneous threshold** uses the `DEVIATION_TIER_BREAKS` edge: 14250 against a 15000 floor is `deviation_pct` exactly `0.0500` → base 1 → 2 points on MARKETPLACE, versus 14249 → `0.0501` → 3.
7. **Cascade chain A enumerated from the scaffold's own link notes** (link 2 Reseller→TERMINATED, link 2b Violations→CLOSED_MOOT, link 3 Agreement→TERMINATED, link 4 SerialUnit→RECALLED). Ordering sensitivity is asserted as the ledger reading 19 after termination (link 2b retains `assessed_points` rather than recomputing to 0); partial failure is the BCM-attempted TERMINATION, where all four levels must be untouched.
8. **`GET` list endpoints carry no `captures:`** — the linter resolves capture paths against a single entity's §1.1 fields, so list-shaped responses are asserted in prose (row counts, page unions, cross-filter equivalences) instead.
9. Five capture paths were corrected against the real §1.1 field names surfaced by the linter: `ResellerAgreement.closed_reason` (not `decline_reason`), `PriceObservation.evaluation_status` (not `status`), `Violation.assessed_floor_cents` (no `corrected_price_cents` field exists), `EnforcementNotice.closed_reason` (not `rescinded_reason`), and `DistributorChargeback.tier_rate_cents_per_unit` (not `tier_rate_cents` — this also fixed two stale prose asserts in the earlier `calculations` section).

### CRITICAL orchestrator finding — the two design indices and the PRD resolved the same four scaffold conflicts in OPPOSITE directions

The frozen `SCAFFOLD.yaml` contradicts itself in four places: its §1.2 `state_machines` triggers and its §1.5 `endpoints[].side_effects` name different enum literals for the same operation. Step 4's doc generator resolved all four toward **§1.2**; the §1.8 agent resolved all four toward **§1.5**. Both stated defensible reasoning. The result is a literal-level divergence between `PRD.md` and the design indices:

| operation | PRD.md says (authoritative) | design indices say |
|---|---|---|
| policy review `decision` | `APPROVE_FOR_PUBLICATION` / `RETURN_FOR_REVISION` | `APPROVE` / `RETURN` |
| violation `dispute-decision` | `REJECT` / `SUSTAIN` | `UPHOLD` / `REVERSE` |
| test purchase `confirm-outcome` | `UNAUTHORIZED` / `AUTHORIZED` | `CONFIRM` / `CLEAR` |
| notice rescind → cited Violation | → `DETECTED` | → `VOIDED` |

Note `scaffold_lint.py` cannot catch this: it validates payload *keys*, roles, endpoints and capture paths, but never enum *values*.

**Adjudication: `PRD.md` wins, unconditionally.** The benchmark's contract is that the implementer reads `PRD.md` and never sees the scaffold, so the PRD's literals are the only ones the implementation can possibly emit. The design indices are a *generation index*, not a contract.

**Instruction carried into Step 5:** where a design instance's asserted rule is PRD-covered but its enum literal is one of the four above, the test generator must **translate the literal to the PRD spelling and keep the test** — not skip it. The underlying rule (a policy review has an approve branch and a return branch, etc.) is verbatim in the PRD; only the token differs, and that difference is an artifact of the scaffold's internal inconsistency. Translating makes the test faithful to the contract, which is exactly what the PRD-First rule demands. Skipping would silently drop a large, legitimately-covered slice of the state-machine section. This is passed explicitly to the Step 5 subagent so it does not have to rediscover it, and it is recorded here so that if Step 7 nonetheless sees these literals it knows the history rather than re-litigating it.

## Step 6: Generate implementation — 2026-09-03T02:04:00.000Z

Launched concurrently with Step 5 in a single assistant message, per the skill's physical-isolation requirement: `test_suite/` did not exist when the implementation agent started, so it could not have read the tests even had it tried. The agent was additionally told explicitly not to read either design index or the test directories, and was given the four-literal PRD-wins table so it would implement the PRD spelling rather than the scaffold's.

### Subagent summary (verbatim)

Implementation complete at `.../workspace/implementation/`.

**Modules (line counts).** Shared core: `app.py` 77, `store.py` 152, `errors.py` 78, `envelope.py` 81, `auth.py` 71, `validate.py` 256, `calc.py` 459, `lookup.py` 101, `cascade.py` 119. Blueprints (`routes/`): `__init__.py` 1, `policies.py` 152, `products.py` 128, `distributors.py` 57, `resellers.py` 135, `agreements.py` 161, `observations.py` 192, `violations.py` 112, `notices.py` 215, `exceptions.py` 204, `serial_units.py` 90, `test_purchases.py` 122, `chargebacks.py` 144, `sweeps.py` 90. Launcher: `start.sh` 14, `requirements.txt` 1. Total 3212 lines, 22 Python files.

**Endpoints.** 61 of the PRD's 61 (`app.url_map` has exactly 61 non-static rules, path-and-method identical to the §4 table, including `PATCH /products/{id}` and `POST /_clock/set_current_utc`).

**Storage.** In-memory only: 12 dicts in `store.py`, created empty by `Store.reset()` at import. An audit for `open(`, `sqlite`, `pickle`, `json.dump`, `/tmp` across all modules returns nothing. Zero seeded entities — on a fresh boot all 12 collection reads return `total_count: 0`. `__pycache__` removed, so the tree holds only source.

**Boot smoke test.** `PORT=17455 bash start.sh` booted Flask on `0.0.0.0` in the foreground; `GET /pricing-policies` returned HTTP 200 with `{"meta":{"api_request_id":"req_…20 chars","api_request_timestamp":"2026-08-01T00:00:00.000Z","limit":10,"offset":0,"total_count":0,"has_more":false},"response_type":"array","data":[]}`. All 12 list endpoints returned 200. Process killed afterwards; `pgrep` shows no strays and a post-kill curl fails to connect.

**Functional verification beyond boot.** I drove three scripted end-to-end walkthroughs (~150 assertions) against fresh servers covering: policy lifecycle incl. supersession/withdrawal, product registration + DISCONTINUED cascade, floor resolution (standard / ALL-scope / channel-scoped / bundle-only / half-open window ends), agreement draft→send→countersign→activate with all three antitrust and ack guards, both reseller state axes, observation capture/evaluate (deviation 4 dp, attribution cap, bundle waterfall allocation 16216), notice issuance at all three rungs, OCC 412s, cooling-off, four-eyes termination (`ERR_TERMINATION_REQUIRES_COUNSEL`, `ERR_SEGREGATION_OF_DUTIES`) with its full cascade, rescission returning the violation to `DETECTED` with a points refund, dispute loop and round cap, cure, retroactive-exception void cascade, override band, serial tracing, test purchases, chargeback tiers/standing breaks/cap 402/reversal, both diversion-exposure variants (incl. 1.20 and 0.80 lot proration), the four-phase sweep and its idempotence, and the auth/pagination ladder. Every discrepancy traced back to a wrong expectation in my scripts, not the implementation — verified against PRD text each time (e.g. unknown `X-User-Role` → `ERR_UNAUTHENTICATED` 401 per §2.1; `clearance_discount_pct` default 0.20; `promo_code_counts_as_advertised` default false so the coupon is the candidate; an `ALL` scope always intersects a channel scope so overlapping windows are 409). No 500s and no unhandled exceptions were observed at any point.

One judgement call worth flagging: on a breach with `matched_reseller_id` null the evaluate response reports `provisional_points: 0`, since the PRD defines that figure as the value stored on the violation row and no violation is created in that branch.

### Orchestrator note

The agent confirms it implemented the PRD spelling for all four contested literals — notably "rescission returning the violation to `DETECTED`", which is the PRD reading and the opposite of the design indices' `VOIDED`. Step 5 was given the matching translation licence, so tests and implementation should agree on this axis. If Step 7 sees `VOIDED` asserted anywhere, that is a Step 5 translation miss and should be fixed in `test_suite/` (STEP 2, test-vs-PRD consistency), not in the implementation.

## Step 5: Generate unit tests — 2026-09-03T03:02:00.000Z

Launched concurrently with Step 6 in a single assistant message. Given the four-literal translation licence described in the Step 2 entry, plus explicit notice that PRD.md §5 (52 error codes, one HTTP status each) and PRD.md §2.1 (six roles) are authoritative because the frozen scaffold has no §1.6/§1.7 block.

### Subagent summary (verbatim)

Verification sweep is complete and the suite is done.

**Files written.** `test_helpers/` — 9 modules, 2,590 lines (`__init__.py` 48, `api_client.py` 258, `api_errors.py` 117, `assertions.py` 570, `constants.py` 122, `factories.py` 375, `fixtures.py` 566, `test_users.py` 72, `types.py` 462), plus `test_suite/conftest.py` 73 lines. `test_suite/` — 29 test modules, 18,039 lines, **419 tests**.

| queue | files | tests | instances |
|---|---|---|---|
| A (Difficulty) | 9 | 59 | 18 / 18 |
| B (Corner) | 20 | 360 | 347 / 355 |

Per corner section (tests / instances covered): entities 43 / 40-of-40 (2 files), state_machines 82 / 82-of-87 (3), calculations 48 / 45-of-45 (3), validations 66 / 66-of-69 (4), endpoints 64 / 64-of-64 (3), errors 14 / 14-of-14 (1), rbac 20 / 18-of-18 (1), cross_cutting_complexity_layers 19 / 15-of-15 (2), consistency_model 4 / 3-of-3 (1).

**Verification results (all green).** `py_compile` clean; `pyflakes` clean (rc=0) on all 29 modules and all helpers; all 29 modules import successfully, so every helper name referenced resolves. 419 docstrings checked: each has exactly one `Design:` line, it is the last line, every tag resolves to a real `- name:` in the correct section's line range of the source yaml, zero untagged/dual-tagged/phantom tags. All PRD citations re-grep verbatim (whitespace-normalized) against `PRD.md`, zero elisions. No duplicate test function names. The word "scaffold" appears nowhere in `test_suite/`. md5 baseline confirms no subagent modified `test_helpers/` or `conftest.py`; `workspace/implementation/` was never read or written; no other task directory was touched.

**Skipped instances (8, all queue B; queue A skipped none).**

state_machines:
- `reseller_terminated_is_terminal_and_supply_status_change_rejected` — asserts `ERR_RESELLER_TERMINATED` for a supply release on a `CUT_OFF`/`TERMINATION` row, but §3.3 assigns that release `ERR_SUPPLY_BLOCKED_BY_AUTHORIZATION` and §2.9 step 7 lists both codes with no precedence: outcome non-unique.
- `policy_publish_with_past_effective_from_rejected` — §3.1 requires `effective_from` ≥ clock but pins no code; `ERR_VALIDATION` (400) vs `ERR_INVALID_STATE` (409) not derivable.
- `serial_ship_downstream_to_held_reseller_rejected` — §3.8 requires target `supply_status` `OPEN` but names no code; `ERR_INVALID_STATE` vs `ERR_SUPPLY_BLOCKED_BY_AUTHORIZATION` non-unique.
- `sweep_executes_all_four_side_effect_families_in_one_call` — phase 1 sets `hold_reason` `AGREEMENT_EXPIRED` while §3.7's reinstatement predicate needs `SUSPENSION`, so `reinstated_resellers` (1 or 0) and the terminal supply state are not uniquely determined in a combined sweep.
- `second_acknowledge_of_the_same_notice_rejected` — §2.9 step 7 lists `ACKNOWLEDGED` among the legal from-states for acknowledgement, contradicting the asserted 409.

validations:
- `notice_citing_a_superseded_policy_rejected` — needs a second policy reusing `policy_code`, which §3.1 uniquely rejects; the asserted `ERR_POLICY_NOT_PUBLISHED` state is unreachable through declared endpoints (this is the `policy_code` uniqueness-vs-supersession contradiction).
- `countersignature_without_the_non_negotiation_ack_rejected` — §3.4 places `ERR_NON_NEGOTIATION_ACK_MISSING` at activation only; the PRD is silent for the `respond` route.
- `suspension_inside_the_cooling_off_period_rejected` — the instance's own computed rung is `TERMINATION`, and §3.7 polices the window and buffer only "When a suspension is being installed"; `ERR_SUSPENSION_COOLING_OFF` not derived.

**Four-literal translation licence.** **2 tests** used it: `test_difficulty_compensating_invariant.py` (rescission returns the cited violation to `DETECTED`, not `VOIDED`) and `test_corner_endpoints_part3.py` (`confirm-outcome` sent as `AUTHORIZED`, not `CLEARED`). Every other section's index already spelled the PRD literals. Chargeback dispute decisions (`UPHOLD`/`REVERSE`) and exception decisions (`APPROVE`/`REJECT`) are genuine PRD wording and were not translated.

**Judgement worth flagging.** Two agents split on the same guard (ship-downstream to a held reseller). I applied the sub-assertion carve-out to queue A's `serial_ship_downstream_gated_by_reseller_supply_axis`: the test keeps the refusal and the untouched-unit assertions but no longer pins a single code, using `validate_error_is_one_of([ERR_INVALID_STATE, ERR_SUPPLY_BLOCKED_BY_AUTHORIZATION])`, so the suite no longer contradicts the corner-side skip of the same rule. Other adjudications made by agents (dropped sub-assertions, setup repairs where an index recipe was self-inconsistent) are recorded in the code comments of the affected tests.

### Orchestrator verification

`grep -c '^def test_' test_suite/*.py` → **419**, matching the subagent's claim. `prd-bench-local-run` confirmed present at `/home/ubuntu/.local/bin/prd-bench-local-run`. The 8 skips are all genuine PRD-silence / non-uniqueness calls with a cited PRD section each, which is exactly the behaviour the PRD-First contract requires — gaps stay gaps. Note that 5 of the 8 skips point at real Zero-Silence gaps in PRD.md (uncoded preconditions, a `§2.9 step 7` from-state list that admits a second reading, and the `policy_code` uniqueness-vs-supersession contradiction inherited from the scaffold); these are feedback for the doc-generator skill and several will be closed by Step 9's completeness pass.

## Step 7: Run tests and iterate — 2026-09-03T03:42:00.000Z

### Subagent summary (verbatim)

All 8 rounds green. Final sweep complete.

**Iterations run:** 2 (iteration 1 diagnosed the union set; iteration 2 verified the fixes)

**Final sweep evidence — 8 parallel rounds, `per-test-server` isolation**

| round | passed/total | failed | errors |
|---|---|---|---|
| results.1.json | 419/419 | 0 | 0 |
| results.2.json | 419/419 | 0 | 0 |
| results.3.json | 419/419 | 0 | 0 |
| results.4.json | 419/419 | 0 | 0 |
| results.5.json | 419/419 | 0 | 0 |
| results.6.json | 419/419 | 0 | 0 |
| results.7.json | 419/419 | 0 | 0 |
| results.8.json | 419/419 | 0 | 0 |

(~730 s per round. Collection is now exactly 419 items; iteration 1 collected 421 because of a naming artifact, see below.)

**Tests deleted.** None. Every failing test in the union set survived STEP 1a (PRD verbatim coverage) and STEP 1b (unique derivability), so no PRD-silence or collapse-pattern deletion was warranted.

**Fixes to `implementation/`**
- `workspace/implementation/routes/observations.py`, `evaluate_observation` — the assignment `provisional_points = points` was nested inside `if observation.get("matched_reseller_id"):`, so an unmatched breach reported `provisional_points: 0`. This was the single root cause of 7 of the 9 failing tests (all the bundle-allocation, attribution-cap, channel-weight and superseded-policy calculation tests, which all capture without a `matched_reseller_id`). Reverses the Step-6 judgement call recorded in the pipeline history. PRD §3.5 justifies the change on three independent points: (a) the response contract enumerates `provisional_points` unconditionally and explicitly qualifies only its neighbour — "the `violation_id` of the violation opened (null when none was), `provisional_points`" — so the deliberate asymmetry says the points figure is not conditional; (b) "The **provisional** figure is computed during evaluation with the instant set to `observed_at`" describes evaluation itself, with storage on the violation row named as a separate consequence; (c) the formula names exactly one zero condition — "if the deviation is zero, the points are zero" — and these breaches have non-zero deviation. The unmatched branch still creates no violation row, per "If `matched_reseller_id` is null, **no** violation row is created at all".

**Fixes to `test_suite/`**
- `test_corner_endpoints_part3.py`, `test_the_sweep_returns_four_zeroes_when_nothing_is_due` — setup was self-defeating (STEP 2). It approves a `PROMOTIONAL_EVENT` exception installing a 13000 floor over Aug 10–Aug 25, pins the clock to Aug 20, then detects a violation on a listing at 14000 and tries to issue a notice. PRD §3.7 recomputes the final points at the issuance clock, where the exception floor of 13000 is in force, so 14000 no longer breaches and the implementation correctly returns `ERR_NO_BREACH_AT_FINAL_FLOOR` ("the recomputed final points must be strictly greater than zero"). Lowered `listed_price_cents` to 12000 so the listing still breaches the exception floor at issuance. Every element of the test's intent is preserved — live agreement, live exception covering the sweep instant, open cure window, four zeroes — and the setup is now PRD-consistent rather than the implementation being weakened.

**Fixes to `test_helpers/`**
- `factories.py`, `test_purchase_payload` — the factory is named after PRD §3.8's "test purchase" entity, so its `test_` prefix collided with pytest's collection rule in the two modules that import it (`test_corner_entities.py`, `test_corner_endpoints_part3.py`), producing 2 collection errors per round (`fixture 'observation_id' not found`) and inflating the collected total to 421. Added `test_purchase_payload.__test__ = False`. Affects both importing modules from one place; no test semantics changed.

**Notes**
- The iteration-1 `sweep.log` name/result tally was misleading: eight pytest processes append to one log, so `FAILED` tokens glue onto neighbouring test names. Two tests (`test_pinning_the_clock_reports_both_sides_of_the_jump`, `test_the_counsel_who_suspended_may_not_also_terminate`) looked like 6/8 and 8/8 failures in the log but never appear as failures in any `results.$i.json` — the JSON is the only reliable source.
- One round-3-only `RemoteDisconnected` on `test_violation_noticed_to_cured_retains_points_and_satisfies_notice` in iteration 1 was load-induced, not a defect: it did not recur in any of the 8 clean rounds.
- No implementation check was removed or weakened, no assertion was downgraded, no skip/xfail added, no data seeded at startup, and storage remains in-memory dicts only.

### Orchestrator verification (independent of the subagent's claims)

Read all 8 `results.$i.json` directly: every round reports `passed 419 / total 419 / failed 0 / errors 0`. Confirmed independently:
- `grep -rn 'pytest.mark.skip\|pytest.mark.xfail' test_suite/ test_helpers/` → **no matches** (no dodged assertions).
- `grep -rn -e sqlite -e pickle -e 'json.dump' -e '/tmp' workspace/implementation/ --include=*.py` → **no matches** (no persistence).
- `store.py` `Store.reset()` creates all 12 collections empty; `store = Store()` at import seeds nothing.
- `grep -c '^def test_' test_suite/*.py` → **419**, matching the collected total, so the `__test__ = False` fix genuinely removed the 2 phantom collections rather than hiding real tests.

Baseline sweep (before any fix) was 410–411 / 421 across the 8 rounds, so the two iterations closed 10 distinct failure signals. Step 8 is **not** skipped: Step 7 applied 1 `implementation/` fix, 1 `test_suite/` fix and 1 `test_helpers/` fix.

## Step 8: Finalize PRD — 2026-09-03T03:53:00.000Z

Not skipped: Step 7 applied one `implementation/` fix, one `test_suite/` fix and one `test_helpers/` fix, so the skip condition (zero fixes, zero deletions, zero iterations) did not hold. The Step 7 worklog entry was inlined verbatim as `<step_7_diff>`, annotated by the orchestrator to mark which of the three fixes carried a PRD implication and which did not, so the agent would not manufacture edits for the two that don't.

### Subagent summary (verbatim)

`PRD_FINALIZED.md` written at `.../workspace/PRD_FINALIZED.md`.

**Size.** PRD.md: 453 lines / 102,178 chars. PRD_FINALIZED.md: 453 lines / 102,871 chars. Line delta 0 (+0.00%); character delta +693 (+0.68%). Two paragraphs touched, both in §3.5.

**Changes**
- **§3.5 (evaluation response contract) — revise — pinned that `provisional_points` is reported on the breach branch regardless of `matched_reseller_id` (and is 0 on the compliant branch), with `violation_id` the only conditional member of that pair — `implementation/routes/observations.py:123,139,170`.**
- **§3.5 (provisional vs final figure) — revise — storage of `provisional_points` scoped to "the violation row whenever one is opened" while reporting is unconditional, plus the repeat weight of an unmatched breach's provisional figure stays at 1.00 — `implementation/routes/observations.py:131-133` calling `implementation/calc.py:188` with `reseller_id=None` → `count_prior_noticed` returns 0.**

Two of the three Step 7 fixes (`test_suite/` fixture bug, `test_helpers/` `__test__ = False`) carry no PRD implication, so nothing was written for them, as anticipated.

**Per-edit pre-edit search log**

*Edit 1 — response contract.*
(a) Subject: the `provisional_points` member of the `POST /price-observations/{id}/evaluate` response, and its dependence on `matched_reseller_id`.
(b) Paths enumerated: `grep -rn "provisional_points\|provisional_floor"` over all of `implementation/` — only `routes/observations.py:123,139,146,147,170` (no other producer or consumer anywhere). Read `evaluate_observation` in full (compliant branch keeps the initializer 0; breach branch assigns unconditionally at line 139; the violation row is still created only inside `if observation.get("matched_reseller_id")`). Read the two sibling readers of the same entity, `read_observation`/`list_observations` — they `serialize(row)` the observation, which carries no points field, so no parallel endpoint surfaces this figure. Checked `routes/products.py:110-128` (computed-floor read) and `routes/resellers.py:113-140` (compliance summary) as the other two computed-read endpoints: neither exposes a provisional figure. Checked `routes/test_purchases.py` end-to-end to confirm the unmatched/test-purchase route never later opens a violation, so "no violation row is created at all" remains true verbatim. Checked PRD endpoint table line 362 ("open a violation on breach") for contradiction — none, it is already reconciled by the existing "only the matched branch produces a violation".
(c) Adjustment: wrote the claim as "reports … on **both** branches of the fork" rather than editing the unmatched-branch sentence in the preceding paragraph, so the existing "**no** violation row is created at all" sentence stays verbatim and the new wording adds nothing about row creation. Verified "non-zero" is a safe universal: the smallest breach product is base 1 × `PHYSICAL_RETAIL` 0.5 × repeat 1.00 = 0.5, which `rhu_int` rounds half up to 1, so no breach can report 0.

*Edit 2 — provisional/final figure paragraph.*
(a) Subject: where the provisional figure is *stored* versus *reported*, and the repeat weight used when there is no matched reseller.
(b) Paths enumerated: both callsites of `calc.violation_points` — `routes/observations.py:131` (provisional, passes `observation.get("matched_reseller_id")`, which may be `None`) and `routes/notices.py:73` (final, always passes a resolved `reseller_id` plus `violation["id"]` as the exclusion). Read `calc.count_prior_noticed` (matches on `viol["reseller_id"] != reseller_id`, so a `None` argument matches nothing) and `calc.violation_points` (repeat multiplier `1.00 + 0.25 * min(prior, 4)`). Verified via `routes/observations.py:141-152` that every violation row is born with a non-null `reseller_id`, so `reseller_id=None` can never coincidentally match a stored row — the 1.00 claim is unconditional, not incidental. Also read the other writers of `violation_points_total` (`calc.py:358`, `cascade.py:24`, `routes/exceptions.py:174`, `routes/notices.py:108`) to confirm none of them recompute or re-store a *provisional* figure, so scoping the storage sentence to "the violation row" mis-describes nothing.
(c) Adjustment: used "on the violation row whenever one is opened" rather than "only when matched", so the sentence stays true for the matched path without asserting a negative about any future/other writer; kept the repeat-weight claim scoped to "that provisional figure" so it cannot be read as constraining the final recomputation at issuance, where a reseller always exists and the tally can be non-zero.

### Orchestrator verification

`diff PRD.md PRD_FINALIZED.md` shows exactly two changed lines (232 and 238), both in §3.5, both pure in-paragraph revisions with no new sections and no structural change. Line count unchanged at 453; +693 chars. This is the correct shape for a Step 8 output whose `<step_7_diff>` contained a single genuine PRD silence — the `provisional_points`-on-unmatched-breach reading, on which Step 6's and Step 7's independent PRD-faithful readers reached opposite conclusions, which is exactly the two-reader signature of non-unique derivability.

## Step 9: Complete PRD — 2026-09-03T04:13:00.000Z

Always runs. Started from `PRD_FINALIZED.md` (Step 8 produced it). The agent was seeded with the six concrete PRD gaps that Steps 5 and 7 had already surfaced from a different angle — the uncoded `effective_from` precondition, the uncoded serial ship-downstream `supply_status` precondition, §2.9 step 7's second-acknowledgement reading, `ERR_NON_NEGOTIATION_ACK_MISSING` placement, the cooling-off window's rung scope, and the `policy_code` uniqueness-vs-supersession contradiction — so the exhaustive walk would not have to rediscover them.

### Subagent summary (verbatim)

Done. `PRD_COMPLETED.md` is finished.

**Accounting.** Source `workspace/PRD_FINALIZED.md`: **453 lines / 102,871 chars**. Output `workspace/PRD_COMPLETED.md`: **453 lines / 110,730 chars** — **+7,859 chars**, **0 lines added**, **0 sections added**. All 49 edits are in-paragraph inserts/revisions touching 42 existing lines (1:1 line replacements, verified by `diff` producing only `NcN` hunks). **49 changes total: 45 ambiguity-pins, 4 mismatch-revisions.**

§2 (8)
- §2.1 — revise — mismatch — ownership guard covers single-row reads/writes only; collection reads are never narrowed to the caller's rows — `auth.py:63-71`
- §2.3 — revise — ambiguity — equal `created_at` tie-break is server insertion sequence — `store.py:138-140`
- §2.3 — insert — ambiguity — a filter value no row carries (incl. off-enum) yields an empty page, not a validation failure — `lookup.py:80-101`
- §2.4 — insert — ambiguity — a row touched several times in one request bumps `version` exactly once — `store.py:120-135`
- §2.8 — revise — ambiguity — version fields must be integers >=1, else `ERR_VALIDATION` — `routes/notices.py:34`, `routes/chargebacks.py:31`
- §2.9 step 7 — revise — mismatch — ack legal only from `ISSUED`; second ack → `ERR_INVALID_STATE`; rescission accepts `ISSUED`/`ACKNOWLEDGED` — `routes/notices.py:170-171,184-185`
- §2.9 step 10 — insert — ambiguity — `ERR_NON_NEGOTIATION_ACK_MISSING` is an activation-only check — `routes/agreements.py:129-130`
- §2.9 step 12 — insert — ambiguity — intra-step order: rung mismatch → counsel → segregation → zero-points — `routes/notices.py:85-99`

§3.1 (5), §3.2 (1), §3.3 (3)
- §3.1 — revise — ambiguity — `policy_code` unique across every status (`ERR_VALIDATION` 400); revisions need fresh codes, supersession still reachable — `routes/policies.py:36-38`
- §3.1 — insert — ambiguity — submit-review threshold recheck is `ERR_VALIDATION` after the DRAFT guard — `routes/policies.py:69-73`
- §3.1 — insert — ambiguity — `legal_review_notes` optional, nulled when omitted — `routes/policies.py:84,88`
- §3.1 — insert — ambiguity — publish with `effective_from` < clock → `ERR_VALIDATION` after the APPROVED guard — `routes/policies.py:105-108`
- §3.1 — insert — ambiguity — `withdrawn_reason` required, non-empty — `routes/policies.py:128`
- §3.2 — insert — ambiguity — empty PATCH is an accepted no-op that still bumps `version`; supplied floor re-bounded >0 and <= `msrp_cents` — `routes/products.py:62-73`
- §3.3 — insert — ambiguity — `probation_entered_at` on re-entry / GOOD / SUSPENDED — `calc.py:288-300`
- §3.3 — revise — ambiguity — HOLD branch codes `ERR_INVALID_STATE` / `ERR_RESELLER_TERMINATED` — `routes/resellers.py:69-75`
- §3.3 — revise — ambiguity — OPEN branch codes, `CUT_OFF` → `ERR_INVALID_STATE`, supplied `hold_reason`/`note` never stored — `routes/resellers.py:64-88`

§3.4 (7)
- `quality_obligations` mandatory but may be empty — insert — ambiguity — `routes/agreements.py:29`
- `term_ends_at` need not be future — insert — ambiguity — `routes/agreements.py:30`
- send requires reseller `APPLIED` → `ERR_INVALID_STATE` — insert — ambiguity — `routes/agreements.py:69-70`
- respond state codes, key-presence antitrust test, ack defaults false, route never polices `non_negotiation_ack_required` — revise — ambiguity — `routes/agreements.py:88-106`
- `decline_reason` optional (`closed_reason` null when omitted) — insert — ambiguity — `routes/agreements.py:89,110`
- activate never inspects the reseller's two axes — insert — ambiguity — `routes/agreements.py:124`
- expiry pushes HOLD/`AGREEMENT_EXPIRED` unconditionally, overwriting `SUSPENSION` — insert — ambiguity — `cascade.py:100-109`

§3.5 (3)
- `allocated_component_price_cents` null at capture, computed at evaluation — revise — mismatch — `routes/observations.py:85,114-119`
- governing `permitted_channels` = most recent ACTIVE agreement; check skipped when none — insert — ambiguity — `calc.py:439-444`, `routes/observations.py:62-66`
- new violation's initial nulls and `dispute_rounds` 0 — insert — ambiguity — `routes/observations.py:141-154`

§3.6 (4)
- `requested_override_floor_cents` integer >=1, required for BUNDLE/PROMOTIONAL_EVENT — insert — ambiguity — `routes/exceptions.py:41,50-52`
- `decision_reason` required on both branches — insert — ambiguity — `routes/exceptions.py:105`
- DISCONTINUED product at approval → `ERR_INVALID_STATE` 409 — insert — ambiguity — `routes/exceptions.py:118-119`
- retroactive void keeps `assessed_floor_cents`/`cure_deadline_at`, sets `closed_reason = RETROACTIVE_EXCEPTION`, does not reinstate — revise — ambiguity — `routes/exceptions.py:168-186`

§3.7 (11)
- missing suspension window is a late `ERR_VALIDATION` after state/version/antitrust/referential checks; WARNING/TERMINATION store any window verbatim — revise — ambiguity — `routes/notices.py:80-84,119-120`
- "governing suspension notice" = most recent non-`RESCINDED` SUSPENSION notice, any status; none ⇒ check passes — revise — ambiguity — `calc.py:244-251`, `routes/notices.py:92-96`
- 90-day duration is a shape-stage check for any rung — revise — ambiguity — `routes/notices.py:38-42`
- intersection + cooling-off apply only to a computed `SUSPENSION` rung — insert — ambiguity — `routes/notices.py:80-84`
- second acknowledgement → `ERR_INVALID_STATE` — insert — ambiguity — `routes/notices.py:170-171`
- cure `corrected_price_cents` integer >=0 — revise — ambiguity — `routes/violations.py:28`
- cure satisfies the notice only if still `ISSUED`/`ACKNOWLEDGED` — insert — ambiguity — `routes/violations.py:42-46`
- REJECT extends from the stored `cure_deadline_at`, keeps `dispute_reason` — revise — ambiguity — `routes/violations.py:81-83`
- SUSTAIN rescission records `closed_reason = DISPUTE_SUSTAINED`, guarded on `ISSUED`/`ACKNOWLEDGED` — revise — ambiguity — `routes/violations.py:90`, `cascade.py:45-49`
- sweep phase 4 satisfies the most recent `ISSUED`/`ACKNOWLEDGED` SUSPENSION notice; reinstates and counts even when none exists — revise — ambiguity — `sweeps.py:71-76`, `calc.py:254-261`
- compliance summary: `highest_issued_rung` null when empty, `next_rung` off the stored total, threshold provenance chain (ACTIVE agreement's policy → any agreement's policy → policy governing `as_of` → 6/12), `as_of` steers nothing else — revise — ambiguity — `routes/resellers.py:114-135`, `calc.py:447-458`

§3.8 (3)
- registration advances the named distributor's `version` — insert — ambiguity — `routes/serial_units.py:47-48`
- non-`SHIPPED_TO_DISTRIBUTOR` unit and non-OPEN target reseller both → `ERR_INVALID_STATE` — insert — ambiguity — `routes/serial_units.py:60-63`
- future `ordered_at` → `ERR_VALIDATION` — insert — ambiguity — `routes/test_purchases.py:26-27`

§3.9 (4)
- `score_delta_applied` carried to one decimal, stored with `tier_rate_cents_per_unit` — insert — ambiguity — `routes/chargebacks.py:62-64`
- assessment recomputes `review_required` unconditionally (idempotent), not only on a standing move — revise — mismatch — `routes/chargebacks.py:75`
- reversal likewise unconditional; `dispute_rounds` untouched by REVERSE — revise — mismatch — `routes/chargebacks.py:114-124`
- `variant` is a required query parameter; absent/unrecognized → `ERR_VALIDATION` — revise — ambiguity — `routes/distributors.py:54`, `validate.py:248-256`

**Walk coverage.** All **22** implementation modules were read end to end: `app.py`, `store.py`, `errors.py`, `envelope.py`, `auth.py`, `validate.py`, `lookup.py`, `calc.py`, `cascade.py`, `routes/__init__.py`, and the 13 route modules. Route inventory counted at **61**, exactly matching the §4 table, with authorized-role lists identical — no §4 edit needed. Step 8's §3.5 `provisional_points` edit was verified against `routes/observations.py:123,139,170` and left untouched.

**Deliberately left unpinned**
- `test_purchases.py` `confirm-outcome` guard requiring a non-null `traced_serial_unit_id` for UNAUTHORIZED — unreachable, since reaching `SERIAL_CAPTURED` always sets it.
- `ERR_RESELLER_TERMINATED` on the supply-status HOLD branch — effectively unreachable (a TERMINATED reseller is always `CUT_OFF`, so `ERR_INVALID_STATE` fires first); the code was still pinned in prose, but the unreachability is not.
- Flask's generic handlers mapping unknown paths/methods to `ERR_VALIDATION` with 404/405/500 (`app.py:54-67`) — infrastructure, not domain surface described by the PRD.
- `store.py` internal `_seq` bookkeeping field — never serialized, only its ordering effect was pinned.

### Orchestrator verification

- `wc -l` → `PRD.md` 453, `PRD_FINALIZED.md` 453, `PRD_COMPLETED.md` 453. Line count preserved across both patches, as the minimal-diff contract requires.
- `diff PRD_FINALIZED.md PRD_COMPLETED.md` yields **42 hunks, all of the form `NcN`** — zero add/delete hunks, so every change is a true 1:1 in-paragraph replacement. No new sections and no restructuring.
- Heading count is **28** in `PRD_COMPLETED.md`, identical to `PRD.md`.
- The file ends on `| ERR_OVERRIDE_FLOOR_OUT_OF_RANGE | 422 |` — a complete §5 table row, a real section boundary, not truncated.
- Leak check `grep -in 'harder than expert|expert_plus|SCAFFOLD|test_recipe' PRD_COMPLETED.md` → **no matches**.
- Step 9 wrote only `PRD_COMPLETED.md`; `implementation/`, `test_suite/` and `test_helpers/` are untouched, so the Step 7 green sweep (8 × 419/419) remains the valid evidence of record.

### Pipeline complete

`workspace/PRD_COMPLETED.md` is written. All nine steps are done.

Note for the doc-generator skill's feedback loop: this task's 49 Step 9 pins is a high count, and the distribution is informative — 45 of 49 were *ambiguity* (PRD silent) rather than *mismatch*, concentrated in error-code selection for preconditions the PRD states but leaves uncoded (§3.1, §3.3, §3.6, §3.7 alone account for 23), and in the required/optional shape and server-side default of request fields. That is the same Zero-Silence class that made Step 5 skip 8 design instances. The four genuine mismatches were narrower: the §2.1 ownership guard's scope, §2.9 step 7's acknowledgement from-state list, `allocated_component_price_cents` being deferred to evaluation, and the chargeback routes recomputing `review_required` unconditionally rather than only on a standing move.
