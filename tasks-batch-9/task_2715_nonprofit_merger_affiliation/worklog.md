# Worklog — task_2715_nonprofit_merger_affiliation

## Step 1: Create task directory — 2026-09-04T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2715_nonprofit_merger_affiliation` and `.../workspace` (pre-assigned path; no index scan performed per orchestrator instructions).

## Step 2: Generate Scaffold — 2026-09-04T13:02:00.000Z

All three scaffold artifacts for task 2715 are complete and the lint is clean.

**Verdict block (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2715_nonprofit_merger_affiliation/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2715_nonprofit_merger_affiliation/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2715_nonprofit_merger_affiliation/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     10
  §1.8 instances scanned:     18
  §1.9 instances scanned:     80
  Calls scanned (§1.8+§1.9):  1347

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files**: `SCAFFOLD.yaml` 164,984 B · `SCAFFOLD_DIFFICULTY_DESIGN.yaml` 120,826 B · `SCAFFOLD_CORNER_DESIGN.yaml` 448,105 B. Top-level keys verified: SCAFFOLD.yaml carries neither design key; the other two carry exactly one design key each.

**Domain shape (§1.0–§1.7).** `api_prefix: ""`, `difficulty_level: expert_plus`, archetypes `multi_party_negotiation` / `compliance_audit`, `entity_topology: flat`, `state_machine_shape: cyclic`, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation]`.

**Counts.** 10 entities (Organization, Program, Restructuring, AlignmentAssessment, LetterOfIntent, DiligenceRequest, RestrictedFund, BoardApproval, AGFiling, IntegrationTask) · 8 state machines (LetterOfIntent carries two independent dimensions: `status` and `exclusivity_status`) · 2 §1.2.1 OCC rules (both on `Restructuring.version` via `expected_restructuring_version`, on `POST /letters-of-intent` and `POST /board-approvals`) · 9 calculations · 51 validation rules, priorities 1–51 contiguous, last is `ERR_CLOCK_NOT_MONOTONIC` · 52 endpoints (16 reads / 35 business writes / 1 `/_clock/set_current_utc`) · 51 errors · 7 roles (PlatformAdmin, StrategyOfficer, BoardSecretary, DiligenceLead, CharitableTrustCounsel, StateCharitiesRegulator, IntegrationManager). Verified programmatically: every one of the 51 error ids is asserted in an `assert:` line of some §1.8/§1.9 instance (Table 6's triggerability requirement).

**§1.8 — 9 rule ids × 2 instances = 18.** `dual_variant_calc` (alignment_screening_vs_diligence_adjusted_variant_divergence, restricted_fund_donor_consent_vs_judicial_modification_divergence) · `combinatorial_formula` (reserve_months_requires_per_organization_rounding_before_summation, ag_filing_fee_tier_selected_from_fee_exclusive_provisional_total) · `non_linear_state_machine` (letter_of_intent_counter_revise_cycle_preserves_exclusivity_dimension, restricted_fund_petition_branch_returns_to_modified_not_consent_granted) · `transitive_cascade` (critical_escalation_five_hop_cascade_unwinds_letter_approvals_and_seats, restricted_fund_transfer_four_hop_cascade_releases_held_continuity_task) · `priority_pair_validation_conflict` (select_structure_deal_state_error_precedes_reserve_floor_error, letter_exclusivity_conflict_precedes_seat_split_range_error) · `boundary_precision_check` (ag_petition_threshold_at_exact_boundary_forces_petition_and_45_days, ag_fee_tier_ceiling_one_cent_either_side_of_the_boundary) · `cross_entity_state_dependency` (restricted_fund_transfer_gated_by_the_other_entity_deal_status, integration_task_initial_state_branches_on_the_deal_restricted_posture) · `resource_temporal_overlap` (crew_window_adjacency_allowed_but_one_day_straddle_rejected, exclusivity_cooling_off_window_boundary_for_a_different_counterparty) · `compensating_invariant` (transfer_then_unwind_conserves_the_pair_restricted_corpus, certify_then_rescind_conserves_the_seat_ledger_total).

**§1.9 — nine sections in spec order, 93 instances (80 with recipes, 13 `excluded_because` stubs).** entities 12 (0 stubs) · state_machines 18 (6) · calculations 14 (3) · validations 11 (1) · endpoints 7 (1) · errors 17 (0) · rbac 7 (0) · cross_cutting_complexity_layers 5 (2) · consistency_model 2 (0). Every stub cites a §1.8 instance that exists by name; no name collides across the two design files (111 names total, zero duplicates).

**Design adjudications.** E1–E19 as previously logged. E20 deleted `ERR_SEAT_POOL_EXHAUSTED` (unreachable once seats are drawn from a pool seeded at `combined_board_seats`) and renumbered the ladder to 51. E21 narrowed rule 29. E22 fixed the waive actor. E23 moved the party check on `/respond` to two-party membership. E24 widened `POST /ag-filings` to admit `INTEGRATION` on deal status, because a deal with `ag_review_required == false` passes through `REGULATORY_REVIEW` inside the second certify request and would otherwise make priority 32 `ERR_AG_REVIEW_NOT_REQUIRED` unreachable; rule 32 now documents why. **E25:** both §1.2.1 rule descriptions now state that version arithmetic is per *request*, not per side effect — a request that both writes a child and drives a parent auto-transition moves `Restructuring.version` by exactly 1, and a refused request increments nothing; this makes the OCC corner instances assert exact versions (letters 3→3→3→4, board 6→7→8→9). **E26:** renamed every path placeholder from the descriptive form (`{restructuringId}`, `{organizationId}`, …) to the canonical `{id}` across all three files (209 occurrences). `scaffold_lint.py` check (f) matches the sub-resource reverse-reachability form literally as `GET /<parent>/{id}/<segment>`, so the descriptive names produced 7 spurious `FK_REVERSE_UNREACHABLE` violations even though all seven sub-resource GETs existed. **E27:** added the errors instance `a_fund_whose_historic_dollar_value_exceeds_its_value_is_rejected` after an audit found `ERR_HDV_EXCEEDS_FUND_VALUE` was the one error code no recipe triggered (hdv 48000001 refused, hdv 48000000 accepted — the boundary is exclusive on the upper side only).

## Step 3: Copy Shared Files — 2026-09-04T13:02:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1,424 B).

## Step 4: Generate PRD — 2026-09-04T13:22:00.000Z

PRD complete and all three Hard Contracts pass.

## Output
`workspace/PRD.md` — **471 lines, 104,483 bytes, 13,984 words.** Written incrementally (1 Write + 11 chunked heredoc appends), ends cleanly at the last row of the §5 table. No audit footer, no contract reports in the file. The phrase "harder than expert level" (and any difficulty/scaffold-instruction text) is absent. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

## Sections written
§1 Introduction · §2.1 RBAC · §2.2 API Response Structure · §2.3 Pagination · §2.4 Resource Identity, Timestamps and the Logical Clock · §2.5 Deal-Version Pinning · §2.6 Money, Rounding and Precision · §2.7 Request Admission Order · §2.8 Cascade Discipline and Conserved Quantities · §2.9 Path Resolution for Nested Reads · §3.1–§3.9 (registry, alignment scoring, LOIs/exclusivity, diligence cascade, structure + board ledger, restricted gifts, AG filings, integration/closing, sweeps/abandonment/reconciliation) · §4 Endpoint Definitions · §5 Error Code Catalogue.

## Coverage audit
| Scaffold element | Count | Home |
|---|---|---|
| entities[].fields[].name | 130 unique | §3.1–3.9, all in backticks |
| endpoints[].input identifiers | 86 unique | §3 narratives + §2.3/2.5 |
| path params | `id` | §2.9, §4 |
| state machines / transitions | 8 / 46 | §3.2–3.9 |
| calculations | 9 | §3.1 (corpus, monthly expense), §3.2 (alignment, reserve), §3.5 (vote outcome, seat allocation), §3.6 (transferable amount, posture), §3.7 (consideration/fee, waiting period) |
| validations | 51 | ordering ladder in §2.7 (all 51 numbered + `applies_to` scopes enumerated); substance in §3 |
| concurrency_rules | 2 | §2.5 |
| errors | 51 | §5 table, plus each triggered in narrative |
| roles | 7 | §2.1 |
| endpoints | 52 | §4 table |

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 130 required, 130 present, 0 missing
- endpoints[].input: 86 required, 86 present, 0 missing
- path_params: 1 required, 1 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 51 checked, 51 expressed in prose (§2.7 numbered ladder), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed, 0 missing
- state_machines[].transitions: 46 checked, 46 fully expressed (34 as literal `FROM → TO` arrows, 12 in equivalent prose incl. the dimension-B-only ISSUED→ISSUED exclusivity expiry), 0 missing
- calculations[]: 9 checked, 9 fully expressed (all 24 constants recoverable; floor-vs-round-half-up and pinned evaluation orders stated), 0 missing
- validations[] conditions: 51 checked, 51 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 36 side-effect endpoints + 51 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 130 checked, defaults/initials/computed sources reconstructible, 0 missing
- sibling-branch symmetry: 4 variant groups checked, 4 with equal prose density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- §3 extent: 65,028 chars, 9 subsections
- tokens starting with "/": 0 · bare HTTP-method tokens: 0 · method+path tokens: 0 · bare path-like tokens in prose: 0
Status: PASS
```

Extra precision checks: §2.2 is **byte-identical** to `section-2.2-response-structure.md` (verified by `diff`); §5's 51 rows match `errors[]` id-for-id, status-for-status, **in scaffold order**; §4's 52 rows match `endpoints[]` on method, path, order and role set exactly (programmatic diff, 0 mismatches).

## Adjudications
1. **Header casing** — scaffold writes `X-User-Id`, SKILL.md fixes `X-User-ID`. Used `X-User-ID` and added that header names match case-insensitively.
2. **BoardApproval rescind precondition** — state machine says `status IN {RECORDED, CERTIFIED}`; validation priority 19 says `CERTIFIED` only. Followed priority 19.
3. **Rescind deal-status guard** — the transition forbids rescind on a `CONSUMMATED`/`ABANDONED` deal but priority 16's `applies_to` omits it; documented and attributed to `ERR_INVALID_DEAL_STATE`.
4. **`modified_purpose_code`** — listed in file-petition side effects but is an input only on record-court-decision; assigned to the court-decision step.
5. **Revised `exposure_cents` on respond** — named in the transition, absent from the endpoint input list; documented as optional on the response.
6. **`exclusivity_start_date` not earlier than today** — attributed to `ERR_INVALID_REQUEST` (priority 3, range/format).
7. **AG fee tiers and petition threshold** — expressed in dollars for business embedding ($250 / $1,500 / $5,000; $1M / $10M ceilings; $5M threshold) with an explicit "one hundred cents to the dollar" statement so the cents constants stay exactly reconstructible.
8. **Response-only field names** — dossier fields, sweep response lists (`swept_at`, three id lists) and clock fields (`current_utc`, `previous_utc`) documented in §3.9 / §2.4 even though they are outputs, so Contract 1 holds.
9. **Reserve floor wording** — tightened "at least three months" to "at least `3.00` months … anything strictly below that floor", so `RESERVE_FLOOR_MONTHS = 3.00` and its inclusive comparison are unambiguous.

**Orchestrator truncation check:** `tail -c 1200 PRD.md` ends at the `ERR_CLOCK_NOT_MONOTONIC | 422` row — a real table/section boundary, matching scaffold priority 51 as the last error. 26 headings present through §5. `grep -ci expert PRD.md` = 0 (no difficulty-instruction leak). PRD accepted, no regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-04T14:12:00.000Z

Test generation for task 2715 is complete and verified.

## Files written

**`test_helpers/`** (1,657 lines, 9 files)

| File | Lines |
|---|---|
| `__init__.py` | 48 |
| `api_client.py` | 343 |
| `api_errors.py` | 130 |
| `assertions.py` | 151 |
| `constants.py` | 103 |
| `factories.py` | 347 |
| `fixtures.py` | 375 |
| `test_users.py` | 60 |
| `types.py` | 100 |

**`test_suite/`** (8,582 lines, 23 files, **139 tests**)

`conftest.py` 45 · `test_01_dual_variant_calc` 313/7 · `test_02_combinatorial_formula` 236/6 · `test_03_non_linear_state_machine` 314/7 · `test_04_transitive_cascade` 372/8 · `test_05_priority_pair_validation` 379/7 · `test_06_boundary_precision` 302/6 · `test_07_cross_entity_state_dependency` 262/6 · `test_08_resource_temporal_overlap` 316/6 · `test_09_compensating_invariant` 286/6 · `test_10_corner_entities` 501/12 · `test_11_corner_state_machines` 679/12 · `test_12a_corner_calculations` 481/6 · `test_12b_corner_calculations` 422/5 · `test_13_corner_validations` 649/10 · `test_14_corner_endpoints` 462/6 · `test_15a_corner_errors` 552/8 · `test_15b_corner_errors` 363/4 · `test_15c_corner_errors` 482/5 · `test_16a_corner_rbac` 292/3 · `test_16b_corner_rbac` 353/4 · `test_17_corner_cross_cutting` 328/3 · `test_18_corner_consistency_model` 193/2 (lines/tests)

## Coverage against the two design indices

- **§1.8 difficulty (queue A): 18/18 instances translated, 0 skipped**, across 59 tests. Every instance carries ≥3 tests (skill target is ≥2). No stubs in this file.
- **§1.9 corner (queue B): 80/80 live instances translated, 0 skipped for PRD reasons**, across 80 tests (exactly 1 each). All 13 `excluded_because:` stubs were correctly left untagged and un-emitted: 6 `state_machines`, 3 `calculations`, 1 `validations`, 1 `endpoints` (`the_dossier_read_derives_the_two_variant_scores_and_their_delta`), 2 `cross_cutting_complexity_layers`.

Verification: an AST-based checker confirms exactly one `Design:` line per test, always the last docstring line, well-formed, naming a real non-stub instance — "All tags valid." No occurrence of "scaffold"/"design index" in any generated file. `python3 -m py_compile` passes on all 32 `.py` files; `pytest --collect-only` collects 139 tests with no import or fixture errors.

## Key adjudications (PRD won every time)

1. **Frozen-factory defect found and fixed repo-wide.** `factories.restricted_fund_payload` shipped `restriction_purpose_code="PURP-AFTERSCHOOL"` and `court_decision_payload` shipped `modified_purpose_code="PURP-YOUTHSERVICES"`. PRD §3.6 requires "the same two-letters-hyphen-uppercase-word shape as a mission code", so four letters before the hyphen is invalid and every bare `fx.create_fund` / `fx.setup_fund_*` call would have failed with `ERR_INVALID_REQUEST` against a faithful implementation. I rewrote both defaults (`AF-AFTERSCHOOL`, `YS-YOUTHSERVICES`) and swept all 12 literal overrides in `test_suite/` to conforming codes. A pattern audit over `mission_code`, `restriction_purpose_code`, `modified_purpose_code`, `county_code`, `crew_code`, `ein` and `state_code` literals across all 32 files now reports zero violations.
2. Design-yaml `county_code: "CO-101"`/`"CO-202"` and `crew_code: "CREW-A"`/`"CREW-B"`/`"CREW-C"` violate the PRD's stated shapes; replaced with `CA-ALAMEDA`/`CA-SONOMA` and `CREW-A1`…`CREW-D1`.
3. Yaml `sequence_no`/`pinned_assessment_sequence_no` values of 2 and 3 corrected to 1 and 2: PRD §3.2 counts prior snapshots of the same deal *and same variant*.
4. Yaml asserted the deal-scoped fund listing returns only the transferred fund; PRD §4 defines it as every fund attached to either party "whether as holder of record **or** as transfer recipient", so the total is 2.
5. Yaml prose claims rescission accepts `RECORDED` or `CERTIFIED`; PRD §3.7 permits `CERTIFIED` only. Asserted outcome unchanged; docstring follows the PRD.
6. `dossier.reserve_months` and `composite_delta` are not uniquely derivable from the PRD, so they are never asserted. Absolute deal-`version` assertions were likewise converted to read-before/read-after deltas, since the PRD fixes version arithmetic per request rather than per side effect.

Nothing under `workspace/implementation/` was created, read, or modified, and `workspace/` contains no stray `test_helpers/` or `test_suite/`.

## Step 6: Generate Implementation — 2026-09-04T14:06:00.000Z

Implementation complete and verified. All smoke servers shut down (ports 21715–21719 confirmed free, killed by port-derived PID only); `__pycache__` cleared so the directory holds only source.

**Location:** `workspace/implementation/` — Python 3 + Flask, 20 source files, **3,248 lines**. Storage is in-memory dicts only; the store boots completely empty on every process start (no seeding, no disk, no /tmp).

### Modules (line counts)
| File | Lines | Role |
|---|---|---|
`start.sh` | 10 | guarded `import flask` check + install, then `exec python3 app.py`; binds `0.0.0.0`, `PORT` default 10000 (chmod +x)
`requirements.txt` | 1 | `flask>=2.0`
`app.py` | 74 | `create_app()`, ten blueprints, `strict_slashes=False`, `ApiError`/`HTTPException`/catch-all handlers (404→`ERR_NOT_FOUND`, 405→`ERR_METHOD_NOT_ALLOWED`, 400→`ERR_INVALID_REQUEST`, else `ERR_INTERNAL`)
`errors.py` | 80 | all 51 error codes → HTTP status + default messages, `fail()`
`clock.py` | 104 | logical clock (default `2026-08-01T00:00:00Z`, monotonic, never wall clock), ISO-8601 UTC with exactly 3 fractional digits
`db.py` | 123 | ten collections, `create_row`, `touch` (per-request touched-set so `version` rises at most once per row per request), `serialize`
`response.py` | 55 | `meta`/`response_type`/`data` envelope, `api_request_id` = `req_` + 20 uppercase alphanumerics, pagination meta
`auth.py` | 57 | 7 roles, two entity-backed roles (StrategyOfficer, BoardSecretary), rules 1–2
`validate.py` | 201 | all rule-3 primitives; `re.fullmatch` for EIN/state/mission-code/`CREW-…` patterns
`calc.py` | 184 | all 9 calculations, `Decimal` + `ROUND_HALF_UP` (with the one deliberate `floor` on the 7% endowment slice)
`services.py` | 428 | finders, party resolution, restricted-corpus recomputation, posture derivation, seat ledger, sweep, cascade helpers
`enums.py` | 63 | every declared enum member set
`routes_read.py` | 296 | 16 reads incl. the 16-field dossier
`routes_registry.py` | 133 | organizations, financial restatement, programs, continuity decision
`routes_deal.py` | 245 | restructurings, alignment assessments, select-structure, consummate, abandon
`routes_letters.py` | 242 | LOI issue/counter/revise/execute/withdraw + exclusivity
`routes_diligence.py` | 178 | create/respond/clear/waive/escalate
`routes_funds.py` | 273 | register/seek-consent/record-consent/file-petition/record-court-decision/transfer/unwind
`routes_approvals.py` | 207 | record/certify/rescind
`routes_ag.py` | 132 | filing submit + decision
`routes_tasks.py` | 127 | plan/start/complete
`routes_ops.py` | 35 | regulatory sweep + `_clock/set_current_utc`

### Coverage verified
- **Endpoints: 52/52** registered (16 reads, 35 business writes, 1 clock endpoint) — confirmed against `app.url_map`.
- **RBAC: 52/52 endpoints exercised live against all 7 roles** (364 probes). Every allowed role passes the role gate and every disallowed role returns 403 `ERR_ROLE_NOT_PERMITTED`; **0 mismatches**. Missing/blank/unknown-header cases all return 401 `ERR_UNAUTHENTICATED`.
- **Error codes: 51/51**, programmatically diffed against SCAFFOLD §1.6 — no mismatched statuses, none missing, none extra.
- **Entity fields: 147/147** declared fields across all 10 entities are referenced by the implementation.
- **Validation ladder:** the full 51-rule strictly ascending order, short-circuiting on the first violation, per endpoint.
- **State machines: 8/8**; **Cascades:** depth-5 CRITICAL diligence escalation, depth-4 restricted-fund transfer, abandonment fan-out over 4 child collections; **Conserved quantities:** seat ledger and party-pair restricted corpus; **OCC:** `expected_restructuring_version` on `POST /letters-of-intent` and `POST /board-approvals` only → 412 `ERR_STALE_RESTRUCTURING_VERSION`.

### Smoke test result
`python3 -m py_compile` clean on all 20 `.py` files. Two scripted end-to-end passes (kept in `/tmp`, outside the implementation dir), each on a fresh boot: **FAILURES: 0**. Final fresh-boot check: `GET /organizations` → `{"data":[], total_count:0}` with `api_request_timestamp` `2026-08-01T00:00:00.000Z`, proving an empty store and the default logical clock on every relaunch.

### Adjudications (PRD ambiguities)
1. `board_seat_split_initiator` outside `[1, combined_board_seats-1]` → 422 `ERR_SEAT_SPLIT_OUT_OF_RANGE` on both issuance and revise; non-integer → 400.
2. `recusals > seats_total` → 400 `ERR_INVALID_REQUEST`.
3. `ERR_HDV_EXCEEDS_FUND_VALUE` applies to **all** fund types (PRD §3.6 over the scaffold's priority-31 wording).
4. Rescind requires status `CERTIFIED` only.
5. Rescind's deal-not-terminal check sits at ladder position 16, before rule 19.
6. Letter issuance validates two-party membership only.
7. Blank `fiduciary_memo_ref` on certify → 422 `ERR_CONFLICT_DISCLOSURE_MISSING`; absent/empty → 400.
8. Task start follows global ladder order 16 → 21 → 35 → 43.
9. Transfer basis/status mismatch → `ERR_DONOR_CONSENT_REQUIRED`.
10. Non-`ACTIVE` program on continuity-decision → 422 `ERR_PROGRAM_NOT_DEAL_PARTY_ASSET`.
11. Dossier: missing-variant scores default `0.00`; `reserve_months`/`combined_monthly_expense_cents` come from latest DILIGENCE_ADJUSTED, else latest SCREENING, else `0.00`/`0`.
12. `exposure_cents` on diligence create is optional, default 0.
13. Enum-valued query filters are validated against their declared sets → 400 on an unknown member.
14. Optional-with-default inputs: `confidentiality_tier`=STANDARD; `recusals`/`abstentions`/`conflict_disclosures_count`/`accumulated_appreciation_cents`=0; `restriction_conflict`=false; `donor_of_record_reachable`=true.
15. Free-text reason/note fields must be non-blank strings; `objection_reason` is mandatory and non-blank on an OBJECTED decision → 400.
16. `GET /organizations/{id}/programs` matches `org_id == id` **or** `transferred_to_org_id == id`.
17. `respond` accepts an optional revised `exposure_cents` (PRD sentence, absent from the scaffold input list).
18. Fund mutations silently re-derive restricted posture on other deals of the same party pair without a version bump; only the named deal is touched.
19. Among fund operations, only `transfer` and `unwind` bump `Restructuring.version`.

No files were read, listed, globbed, or grepped under `test_suite/`, `test_helpers/`, or the two design yamls; all writes stayed inside `workspace/implementation/`.

## Step 7: Run Tests and Iterate — 2026-09-04T14:22:00.000Z

All 139 tests pass in all 8 parallel rounds. Only `test_helpers/fixtures.py` was touched — no test deleted, no implementation change needed.

## Summary

**Iterations run:** 2 (sweep → single fix → sweep).

**Tests deleted:** none. All 139 tests survived STEP 1 (PRD coverage + unique derivability); the one failure was a test-harness defect, not a PRD-silence or non-determinism issue.

**Fixes applied to `test_helpers/`:** one file, `test_helpers/fixtures.py`.

Every lifecycle stage helper used the idiom `ctx = ctx or setup_previous_stage(api)`. That treats *any* non-empty ctx as "already at the previous stage", so a caller handing in a partial ctx skips the intervening stages and then dereferences a key that was never built. `test_15a_corner_errors.py::test_select_structure_on_a_not_viable_rating_is_rejected` calls `fx.setup_deal_diligence(api, ctx)` with a ctx holding only the two custom-scored organizations (it needs unrelated mission codes and specific net assets to land a `NOT_VIABLE` rating), so `setup_deal_diligence` skipped exploratory → rationale_built → loi_negotiation and died on `ctx["loi"]` with `KeyError: 'loi'` — deterministically, in all 8 rounds.

Replaced the short-circuit with a guarded prerequisite build in all nine stage helpers (`setup_deal_exploratory`, `_rationale_built`, `_loi_negotiation`, `_diligence`, `_diligence_closed`, `_structure_selected`, `_board_approval`, `_regulatory_review`, `_integration`): each now checks for the specific key/status it is about to consume (`org_a`, `deal`, `screening`, `loi`, `loi.status == EXECUTED`, `finding`, `deal.status == STRUCTURE_SELECTED`, `approval_initiator`, `deal.status in {REGULATORY_REVIEW, INTEGRATION}`) and builds the missing prior stage from the ctx it was given, preserving the caller's custom organizations.

Verified before editing that every other ctx-passing call site (test_02, test_05, test_06, test_07, test_11, test_12b, test_15b, test_15c) hands off from the immediately preceding stage helper, so each new guard is inert on all previously-passing paths — confirmed by the sweep, where the other 138 tests stayed green.

**Fixes applied to `implementation/`:** none. The implementation was already PRD-faithful; the single failure never reached the server (it aborted during fixture setup).

**Final per-round figures — all 8 rounds 139/139 passed, 0 failed, 0 errors:**

| round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 139/139 | 139/139 | 139/139 | 139/139 | 139/139 | 139/139 | 139/139 | 139/139 |

Note from the subagent: the runner does not accept a `-k` selector, so targeted spot-checks aren't possible — every verification is a full 8-round sweep (~5 min wall time under the host's concurrent load).

**Orchestrator independent verification:** all 8 `results.$i.json` exist (≈40 KB each, written 14:21) and were re-parsed directly — every round reports `total 139 / passed 139 / failed 0 / errors 0 / skipped 0`. The sweep artifacts are real, not a subagent claim.

**Step 8 decision:** NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes; Step 7 applied one `test_helpers/fixtures.py` fix, so Step 8 runs. Because there were 0 `implementation/` fixes, a byte-identical or near-identical `PRD_FINALIZED.md` is a legitimate outcome here — the alignment target never moved.

## Step 8: Finalize PRD — 2026-09-04T14:28:00.000Z

`PRD_FINALIZED.md` is written and is **byte-identical to `PRD.md`** — that is the correct output here; no edits were manufactured.

## Counts
- `PRD.md`: 471 lines; `PRD_FINALIZED.md`: 471 lines; delta **0 lines / 0.0%**; identical md5 `2b87d94e935d4fc98f4722a7ec80276a`.

## Changes
- None.

## Why no edit traces to the Step 7 diff
The single Step 7 item was a test-harness defect only, and it does not surface any PRD silence or PRD/impl mismatch:

1. **Subject identified** — the lifecycle-stage prerequisite chain that `test_helpers/fixtures.py` drives (exploratory → screening snapshot → LOI issue → LOI execute → finding/respond/clear → select-structure → board approvals → certification → AG filing), plus the specific behavior the failing test asserts: `POST /restructurings/{id}/select-structure` refusing a `NOT_VIABLE` latest `DILIGENCE_ADJUSTED` rating with `ERR_ALIGNMENT_RATING_INSUFFICIENT` ahead of the reserve-floor check.

2. **Impl paths enumerated / read** —
   - `implementation/routes_deal.py:100-133` (`select_structure`): party check → `DILIGENCE_CLOSED` status gate → rule 44 `executed_letter_highest_round` → rule 48 latest-`DILIGENCE_ADJUSTED` rating in `{STRONG, MODERATE}` → rule 49 `reserve_months` vs `calc.RESERVE_FLOOR_MONTHS`. Order and codes match PRD §3.5 and ladder items 44/48/49 verbatim.
   - `routes_deal.py:144-170` (`consummate`) — the parallel deal-status/gate ladder, unchanged and PRD-consistent.
   - `routes_approvals.py:140-170` (certification seat draw + both-parties-certified progression, including the `ag_review_required == false` continuation `REGULATORY_REVIEW → INTEGRATION` in the same request) — the behavior the new `setup_deal_integration` / `_regulatory_review` guards key off; PRD §3.5 already pins it explicitly.
   - `services.py` helpers used by those guards (`latest_assessment`, `executed_letter_highest_round`, `deal_approvals`, posture recompute at `services.py:401`) — all consistent with PRD §3.2/§3.5/§3.6 prose.
   - `test_helpers/fixtures.py:116-312` — every added guard checks a ctx key/status it is about to consume and then calls the same PRD-specified endpoints in the same PRD-specified order. Nothing in the fix depends on a behavioral choice the PRD leaves open; the old `ctx = ctx or setup_previous_stage(api)` idiom was simply wrong Python plumbing for a caller-supplied partial ctx.
   - `test_suite/test_15a_corner_errors.py:400-492` — every asserted number (12.00 mission for unrelated codes, 0.00 overlap on an empty admitted set, 4.94 / 5.00 `reserve_months`, 20.00 sustainability for the 3–6 month tier, 32.00 composite banding to `NOT_VIABLE`, `sequence_no` 2 for the second same-variant snapshot, open-exposure netting over `OPEN|RESPONDED|ESCALATED` only) is uniquely derivable from PRD §3.2 and §3.5 as already written.

3. **Wording adjustment** — none needed, because no sentence was added or revised. Zero implementation fixes were applied in Step 7, and the one failure aborted during fixture setup without ever reaching the server, so there is no impl-pinned choice left undescribed by the PRD at that site.

**Orchestrator note:** byte-identical `PRD_FINALIZED.md` is the legitimate Step 8 outcome when Step 7 made zero `implementation/` fixes — the alignment target never moved. Step 9, by contrast, always performs a full scan and must not come out identical without an explicit scan record.

## Step 9: Complete PRD — 2026-09-04T15:05:00.000Z

Run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place). Partition: pass 1 = app/auth/response/errors/enums/clock/db/validate/routes_registry/routes_deal/routes_ops · pass 2 = calc/services/routes_letters/routes_diligence/routes_funds · pass 3 = routes_approvals/routes_ag/routes_tasks/routes_read.

**Totals: 54 substantive changes — 37 ambiguity-pins, 17 mismatch-revisions.** `PRD_FINALIZED.md` 471 lines / 104,483 chars → `PRD_COMPLETED.md` 471 lines / 118,571 chars (**+14,088 chars, +13.5%**; line count unchanged — every change was an in-paragraph insert or revision, no new sections).

### Pass 1 (16 changes: 14 pins, 2 revisions)
- `§2.1` — insert — ambiguity — header *values* whitespace-stripped; empty/whitespace-only header counts as absent (→ `ERR_UNAUTHENTICATED`) — `auth.py:33-39`
- `§2.2` — insert — ambiguity — `api_request_id` = `req_` + exactly 20 uppercase letters/digits — `db.py:53-55`
- `§2.3` — insert — ambiguity — ordering-key ties break by ascending insertion sequence (also on `sequence_no`/`round_no` lists) — `db.py:109-112`
- `§2.4` — insert — ambiguity — `updated_at == created_at` on a never-mutated row — `db.py:62-66`
- `§2.4` — insert — ambiguity — `created_at`/`updated_at` read from the logical clock — `db.py:62,101`
- `§2.4` — insert — ambiguity — `current_utc` accepts no-`Z`, 0–9 fractional digits, `±HH:MM` offsets (normalised to UTC); responses render canonically — `clock.py:12-15,65-85`, `routes_ops.py:26`
- `§2.7 rule 3` — insert — ambiguity — absent/empty body = `{}`; `Content-Type` not inspected; non-object JSON rejected here; explicit `null` on optional = absent; empty-string query param = absent; undeclared fields/params ignored — `validate.py:22-36,75-78,166-184`
- `§2.7 rule 27` — **revise** — **mismatch** — rule 27 also carries the program-still-`ACTIVE` condition, all three answering `ERR_PROGRAM_NOT_DEAL_PARTY_ASSET` from one position — `routes_registry.py:126-128`
- `§3.1` — insert — ambiguity — `restatement_reason` required/non-blank but not persisted, not returned — `routes_registry.py:59`
- `§3.2` — insert — ambiguity — restructuring creation not rule-13-guarded; `X-User-ID` need not equal `initiator_org_id` — `routes_deal.py:22-30`
- `§3.8` — **revise** — **mismatch** — non-`ACTIVE` program on continuity → `ERR_PROGRAM_NOT_DEAL_PARTY_ASSET`, not a state error — `routes_registry.py:126-128`
- `§3.8` — insert — ambiguity — `closing_memo_ref` required/non-blank but recorded nowhere — `routes_deal.py:148`
- `§3.9` — insert — ambiguity — each of the three sweep id lists is in ascending insertion sequence — `services.py:391,405,414`
- `§3.9` — insert — ambiguity — abandonment unwind also recomputes `unresolved_restricted_fund_count`/`restricted_asset_posture` (posture leaves `CLEARED`); continuity hold-back is a no-op as tasks were already cancelled — `routes_deal.py:235-243`
- `§4 preamble` — insert — ambiguity — trailing slash resolves to the same endpoint — `app.py:28`
- `§5 preamble` — insert — ambiguity — three off-catalogue ids in the same envelope: `ERR_NOT_FOUND` 404 (unrouted path), `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 — `app.py:46-64`

Pass 1 verified-already-pinned (nontrivial): all 27 enum tuples in `enums.py` match PRD verbatim; `errors.py` `ERROR_HTTP` is a member-for-member, status-for-status match with the §5 catalogue (51 ids); envelope shape, `data: {}` for empty, error `meta`'s two fields, `has_more = (offset + page) < total_count`; pagination bounds; rule-13's guard list pinning by omission that program registration and assessment creation do no ownership check; clock default `2026-08-01T00:00:00Z`, inclusive monotonicity, no transition on set; version-per-request (`db.touch` at-most-once per row).

### Pass 2 (18 changes: 12 pins, 6 revisions)
- `§2.6` — insert — ambiguity — stated width is rounding precision, not spelling: each ratio/score is a JSON number, trailing zeros not preserved (`0.6000`→`0.6`) — `calc.py:60`, `services.py:341-352`, `routes_approvals.py:74-75`
- `§2.7 rule 4` — **revise** — **mismatch** — dropped the non-existent `transferred_to_org_id` body field and the two operations that never call `find_org` — `routes_funds.py:196-224`, `routes_registry.py:105-128`
- `§2.7 rule 26` — **revise** — **mismatch** — recipient is derived, not supplied; the rule is one membership test on `fund.org_id` — `routes_funds.py:216-224`
- `§2.8` — insert — ambiguity — re-deriving a computed figure is not a "touch" for the `updated_at`/`version` rule — `services.py:105-153`
- `§3.1` — insert — ambiguity — corpus recompute bumps org `version` only when the figure changes; transfer/unwind always stamp both party orgs (`force=True`) — `services.py:105-118`, `routes_funds.py:238`, `services.py:289`
- `§3.3` — insert — ambiguity — "most recent" released/expired window = latest `exclusivity_end_date`, insertion-sequence tie-break, only that one window examined — `routes_letters.py:79-104`
- `§3.3` — **revise** — **mismatch** — independence example changed from `EXPIRED`+`ISSUED` to `EXPIRED`+`EXECUTED` (the former is unreachable) — `services.py:406-416`
- `§3.3` — insert — ambiguity — `counter_note` required, non-blank, persisted nowhere — `routes_letters.py:148`
- `§3.3` — insert — ambiguity — `executed_note` optional, non-blank if supplied, persisted nowhere — `routes_letters.py:189`
- `§3.3` — insert — ambiguity — execution is not rule-16-guarded: past `LOI_NEGOTIATION` the letter still executes and the deal row is untouched — `routes_letters.py:212-220`
- `§3.4` — insert — ambiguity — `clearance_note` required, non-blank, persisted nowhere — `routes_diligence.py:88`
- `§3.4` — **revise** — ambiguity — *every* `EXECUTED` letter is superseded on hop three, not "the" one — `routes_diligence.py:167-171`
- `§3.5` — insert — ambiguity — governing-letter tie on `round_no` *and* `created_at` breaks to the last-inserted row — `services.py:230-236`
- `§3.6` — insert — ambiguity — `modified_purpose_code` optional (stays null when omitted), discarded on a `DENIED` decision — `routes_funds.py:159-186`
- `§3.6` — insert — ambiguity — transfer hop three fans posture recompute out to every other restructuring involving either party — `routes_funds.py:248`
- `§3.6` — insert — **mismatch** — recompute is registry-wide and status-blind (terminal deals included) and does not mutate the deal row: only transfer and unwind raise `Restructuring.version`; registration/solicitation/consent/petition/court-decision leave `updated_at` and `version` standing even when posture changes — `services.py:132-153`, `routes_funds.py:242,272`
- `§3.6` — insert — ambiguity — `unwind_reason` required, non-blank, persisted nowhere; posture fan-out to other deals — `routes_funds.py:262`, `services.py:293`
- `§3.9` — insert — **mismatch** — the three sweep passes run filings → lapse → expiry and the order is observable: a lapsed letter is already `RELEASED`, so an `ISSUED`/`COUNTERED` letter is never reported as expired; the two letter lists are disjoint and `EXPIRED` is reachable only on an `EXECUTED` letter — `services.py:394-416`

Pass 2 verified-already-pinned (nontrivial): fee tiers and strict-`<` ceilings, `required_filing_type` thresholds, both waiting-day surcharges, the `//10000` endowment truncation vs half-up elsewhere, `overlap_index` rounded-then-capped, `overlap_points` peak formula, four sustainability tiers and four rating bands, `reserve_months` zero-denominator case, per-org-then-sum monthly expense, `ceil(eligible/2)` quorum, inclusive `>=` ratio comparison, party-fund set definition and the four-branch posture order, transfer's rule 18/26/29/30 ordering, unwind's rule-16-before-18 ordering, `reevaluate_diligence_closure`'s at-least-one-finding condition, the `RESPONDED ↔ ESCALATED` cycle.

### Pass 3 (20 changes: 11 pins, 9 revisions)
- `§2.7 rule 3` — insert — ambiguity — body reference fields must be non-blank strings at this position, so a blank reference is 400 not 404 — `routes_approvals.py:21`, `routes_tasks.py:26,32`, `routes_ag.py:30`
- `§2.7 rule 16` — **revise** — **mismatch** — guard list was missing diligence-finding escalation and board-approval rescission; added, plus an explicit negative list — `routes_approvals.py:186`, `routes_diligence.py:142`
- `§2.7 rule 35` — **revise** — **mismatch** — also guards integration-task start, with the looser condition (clearance only, no objection test) — `routes_tasks.py:97`
- `§2.7 rule 36` — **revise** — **mismatch** — memo check is intra-position second; its blankness is answered here rather than at rule 3 — `routes_approvals.py:126,129`
- `§2.7 rule 50` — **revise** — **mismatch** — `legal_costs_cents >= 0` is a rule-3 declared-range check (`ERR_INVALID_REQUEST`), not part of this rule — `routes_ag.py:33`
- `§3.1` — insert — **mismatch** — an organization's program list admits programs whose `transferred_to_org_id` is that organization — `routes_read.py:53`
- `§3.5` — insert — ambiguity — the first resolution advances `STRUCTURE_SELECTED → BOARD_APPROVAL` whether the vote came out `APPROVED` or `REJECTED` — `routes_approvals.py:97`
- `§3.5` — **revise** — **mismatch** — `fiduciary_memo_ref` (≥1 char, no upper bound) is the sole field whose blankness escapes rule 3: `""` → `ERR_INVALID_REQUEST`, whitespace-only → `ERR_CONFLICT_DISCLOSURE_MISSING` at position 36; `certifying_secretary_ref` pinned at 1–64 and non-blank — `routes_approvals.py:108,129` (confirmed `non_blank=False` occurs exactly once in the whole impl, so the claim stays local)
- `§3.5` — insert — ambiguity — rescission reverts only from `REGULATORY_REVIEW`; a deal already in `INTEGRATION` keeps its status while deal and org `version` rise regardless — `routes_approvals.py:199-206`
- `§3.6` — insert — ambiguity — the five fund list-filters are exact matches on the currently stored value with no history, so an unwound fund stops matching recipient/authorising-deal filters — `routes_read.py:215-218`
- `§3.7` — insert — ambiguity — a `state_code` that is not exactly two uppercase letters is refused at rule 3, never reaching the applicability test — `routes_ag.py:31`
- `§3.7` — insert — ambiguity — the zero-asset refusal loses to the earlier filing-type mismatch — `routes_ag.py:63-70`
- `§3.7` — insert — ambiguity — submitting a filing writes only the filing row; the deal's `updated_at`/`version` do not move — `routes_ag.py:81`
- `§3.7` — **revise** — **mismatch** — the deal-side half of an approval is conditional on the deal standing in `REGULATORY_REVIEW`, so an approval on a late filing against an `INTEGRATION` deal leaves the deal row untouched; `objection_reason` alongside `APPROVED` is discarded — `routes_ag.py:107,120-126`
- `§3.8` — insert — ambiguity — task `title` must also be non-blank — `routes_tasks.py:29`
- `§3.8` — insert — ambiguity — `planned_end_date <= planned_start_date` is `ERR_INVALID_REQUEST` at position 3, before the deal or predecessor is resolved — `routes_tasks.py:34`
- `§3.8` — insert — ambiguity — planning a task touches only the task row — `routes_tasks.py:65-78`
- `§3.8` — **revise** — **mismatch** — start's gates reordered to true ladder order (deal state 16 before task state 21), the AG gate's looseness versus consummation made explicit, completion pinned as having no deal-status gate, both notes non-blank-where-supplied and never persisted — `routes_tasks.py:85,90-99,117`
- `§4 table` — **revise** — **mismatch** — `/organizations/{id}/programs` description rewritten to cover recipient programs — `routes_read.py:53`
- `§3.9` — **revise** — ambiguity — dossier derivation pinned: each score from the highest-`sequence_no` snapshot of its variant, `0.0` when absent; `composite_delta` = adjusted − screening (may run negative); `reserve_months`/`combined_monthly_expense_cents` from the latest `DILIGENCE_ADJUSTED` else the latest `SCREENING` else `0.0`/`0` — `routes_read.py:264-287`

Pass 3 resolved without an edit: `routes_ag.py` feeds `transferred_charitable_asset_value_cents` to both `statutory_waiting_days` and `required_filing_type`, which §3.7 already calls "the recited asset value" in both places, sharing the one $5,000,000 constant. The routed vote-tally/quorum/no-eligible-votes order already matches §3.5 and ladder rules 36–39 exactly.

### Final integrity check — PASS
26 headings through §5; ends at `` | `ERR_CLOCK_NOT_MONOTONIC` | 422 | ``; §4 table 54 rows (2 header + 52 endpoints); §5 catalogue 53 rows (2 header + 51 codes); zero hits for SCAFFOLD / difficulty / design-index / diff markers; the only odd-backtick lines are the four ```json fences.

**Orchestrator independent verification:** `PRD_COMPLETED.md` = 471 lines / 118,571 chars, md5 `41c56c66…`, distinct from `PRD_FINALIZED.md`/`PRD.md` md5 `2b87d94e…` — the scan genuinely ran (102 diff-marked lines, i.e. 51 revised lines). 26 headings present, tail ends on the `ERR_CLOCK_NOT_MONOTONIC | 422` row, and `grep -ci 'scaffold|harder than expert'` = 0. Pipeline complete.
