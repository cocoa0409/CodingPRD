# Worklog — task_2213_affiliate_homeownership_program_sweat_equity

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2213_affiliate_homeownership_program_sweat_equity/` and its `workspace/` subdirectory (pre-allocated name used verbatim; no index scan performed).

## Step 3: Copy shared files — 2026-09-01T02:05:00.000Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md` (53 lines). Performed out of order (ahead of Step 2) because it has no dependency on the scaffold.

## Step 2a: Generate SCAFFOLD.yaml — 2026-09-01T03:20:00.000Z

Two prior attempts at a combined Step 2 (all three YAML files in one subagent) were killed by the stream watchdog after 600s of no tool activity — both died immediately after beginning to read the 73KB SKILL.md, before writing any bytes. A health probe confirmed background subagents were otherwise fine (4s round trip). Step 2 was therefore split into 2a (SCAFFOLD.yaml) and 2b (the two design indices), and the subagent was given an anti-stall protocol: read SKILL.md in ~150-line chunks via offset/limit, emit a tool call at least every ~60s, and flush output to disk every ~200 lines instead of composing one giant Write.

Subagent summary (verbatim):

Done. `SCAFFOLD.yaml` — 2901 lines, §1.0–§1.7 only, no `scaffold_difficulty_design` / `scaffold_corner_design` keys.

**Counts**
- Entities: **13** — AffiliateProgram, ApplicantHousehold, HouseholdMember, SelectionReview, SweatEquityEntry, BuildSite, ConstructionShift, VolunteerProfile, ShiftAssignment, EducationEnrollment, MortgageApplication, CostEntry (`common_fields: false`, id + created_at only), GrantAward.
- Calculations: **14**. Validations: **44** (strictly increasing priorities, no dupes). Endpoints: **71**. Error catalog: **71** ids. OCC rules: **4** (all `expected_<parent>_version` -> 412). RBAC roles: **7**.

**State machines: 9** (two entities carry two independent dimensions each)
1. ApplicantHousehold.selection_status — DRAFT, SUBMITTED, SCREENING, COMMITTEE_REVIEW, SELECTED, WAITLISTED, DENIED, PARTNERSHIP_ACTIVE, CLOSED
2. ApplicantHousehold.partnership_readiness — NOT_READY, EDUCATION_IN_PROGRESS, EDUCATION_COMPLETE, CLOSING_READY, WITHDRAWN
3. SweatEquityEntry.status — CLAIMED, VERIFIED, CREDITED, REJECTED, REVERSED
4. BuildSite.readiness_status — RAW_LAND, TITLE_CLEAR, ENV_CLEARED, READY_TO_BUILD, UNDER_CONSTRUCTION, SAFETY_HOLD, COMPLETED
5. ConstructionShift.status — SCHEDULED, OPEN, LOCKED, COMPLETED, CANCELLED
6. ShiftAssignment.status — RESERVED, CONFIRMED, CHECKED_IN, COMPLETED, CANCELLED, NO_SHOW
7. EducationEnrollment.status — ENROLLED, IN_PROGRESS, COMPLETED, EXPIRED, FAILED
8. MortgageApplication.status — DRAFT, UNDERWRITING, APPROVED, CLEARED_TO_CLOSE, CLOSED, DENIED, SUPERSEDED
9. MortgageApplication.lien_status — NONE, ACTIVE, FORBEARANCE, TRANSFER_PENDING, SATISFIED, RECAPTURED

**RBAC roles:** ProgramAdmin (opaque), FamilyServicesCoordinator (opaque), SelectionCommitteeMember (opaque), MortgageOfficer (opaque), ConstructionManager (opaque), Applicant (`entity_backed:ApplicantHousehold`), Volunteer (`entity_backed:VolunteerProfile`) — segregation-of-duties model with three enforced separations (self-verification of hours, reviewer vs. decider, structurer vs. approver).

**Linter verdict** (run with empty-list stubs for the two design files, since `_load_yaml` hard-exits if they are absent):
```
Coverage
  §1.5 endpoints declared:    71
  §1.1 entities declared:     13
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Issues found and fixed during the pass:** PyYAML rejects bare `field?` in flow sequences — quoted all 29 affected `input:` lines; minor sweat-equity category eligibility in §1.6 contradicted the §1.3 formula (RESTORE_STORE/ADVOCACY only) and the category caps were mis-attributed; `ERR_MEMBER_NOT_ACTIVE` referenced a non-existent `is_active` field; §1.3 subsidy ledger trigger named stale lien actions; `CostEntry.VOIDED` was unreachable (added `POST /cost-entries/{id}/void`, endpoint 71) and the entity lacked explicit id/created_at; one forbidden concurrency phrase ("in parallel") and three vague "live row" phrasings were replaced with enumerated statuses; renamed `ERR_INVALID_STATE` -> `ERR_TRANSITION_NOT_ALLOWED` per the domain-naming principle. Verified: every error id is both cataloged and triggerable, all HTTP statuses agree across §1.3/§1.4/§1.6, all 20 FK descriptions carry the canonical `FK -> {Parent}.id` prefix, and every endpoint path referenced in §1.2/§1.2.1/§1.3/§1.4 resolves to a declared §1.5 endpoint.

**Orchestrator post-verification:** parsed the YAML and found 3 lines of debris appended past the end of the roles section — a stray `error_id: ERR_STALE_PROGRAM_VERSION` / `http_status: 412` pair that YAML had silently absorbed as two extra keys on the final `Volunteer` role mapping. `ERR_STALE_PROGRAM_VERSION` was already correctly cataloged at line 2579 under the section's real `id:`/`http:` key names, so the fragment was a duplicate from a misfired append, not a missing entry. Removed it; file is now 2898 lines and re-parses with the Volunteer role carrying exactly its 6 intended keys. Verified counts: 13 entities, 9 state machines, 4 concurrency rules, 14 calculations, 44 validations, 71 endpoints, 71 errors, 7 roles.

## Resume checkpoint — 2026-09-01T04:00:00.000Z

Pipeline resumed after crash. On-disk audit at resume time:

| Artifact | Verdict |
|---|---|
| `SCAFFOLD.yaml` | **VALID** — 2898 lines, parses, 13 entities / 9 state machines / 4 concurrency rules / 14 calculations / 44 validations / 71 endpoints / 71 errors / 7 roles; no design keys present |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | **TRUNCATED** — 605 lines, parses, but carries only 4 of the 9 required §0.5 rules (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`). Rules 5–9 (`priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`) absent. Rule 4 itself is complete, so the file is a clean prefix — resumable by append rather than regeneration. |
| `SCAFFOLD_CORNER_DESIGN.yaml` | **MISSING** |
| `workspace/INSTRUCTION.md` | **VALID** — 53 lines, byte-identical to project-root `INSTRUCTION.md` |
| `workspace/PRD.md` | **MISSING** |
| `test_helpers/`, `test_suite/`, `workspace/implementation/` | **MISSING** |
| `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md` | **MISSING** |

Resume plan: Step 2b split three ways to stay under the stall watchdog that killed the two earlier combined attempts — rules 5–7 and rules 8–9 generated as separate concatenable fragments by two concurrent subagents, then the corner design (which must cite completed difficulty-instance names in its `excluded_because:` stubs) generated afterward. Step 4 (PRD) launched concurrently with the fragments: it reads only `SCAFFOLD.yaml`, which is already valid, and both design indices are withheld from it, so it has no dependency on Step 2b's completion.

## Step 2b: Complete SCAFFOLD_DIFFICULTY_DESIGN.yaml (rules 5–9) — 2026-09-01T04:05:00.000Z

Generated as two concatenable fragments by two concurrent subagents (rules 5–7 and rules 8–9), then appended to the existing 605-line prefix by the orchestrator. Final file: **1449 lines, 9 rules, 21 instances, zero duplicate instance names**; every instance carries `grounds`, `distinguishing_aspect`, and a `test_recipe` with all four of `setup` / `setup_api_calls` / `trigger` / `assert`.

### Subagent summary — rules 5–7 (verbatim)

Done.

## Deliverable

`_frag_rules_5_7.yaml` — **551 lines**, exactly 3 top-level list items at 2-space indent, no `scaffold_difficulty_design:` key, no lines at column 0. 166 structured call objects. `SCAFFOLD.yaml` and `SCAFFOLD_DIFFICULTY_DESIGN.yaml` were not touched.

## rule_id → instances, with the "must differ" discriminator

**`priority_pair_validation_conflict`** (3 instances, three pairwise-distinct error-category pairs):
1. `frozen_program_priority_12_beats_subsidy_exhaustion_priority_38` — **state (p12 `ERR_PROGRAM_FROZEN`) vs business_fiscal (p38 `ERR_SUBSIDY_POOL_EXHAUSTED`)**. Single `POST .../approve` with program SUSPENDED *and* available 1000000 < silent second 1950000 → 409 `ERR_PROGRAM_FROZEN`, `ERR_SUBSIDY_POOL_EXHAUSTED` never returned. (Scaffold's declared PAIR A.)
2. `waiver_expiry_priority_28_beats_volunteer_double_booking_priority_29` — **business_safety (p28 `ERR_WAIVER_EXPIRED`) vs business_temporal (p29 `ERR_VOLUNTEER_DOUBLE_BOOKED`)**. Waiver expires 2026-08-10T12:00Z; candidate shift starts 13:00Z and its `[13:00,17:00)` interval intersects the volunteer's existing RESERVED seat on `[08:00,16:00)` → 422 `ERR_WAIVER_EXPIRED`. (Declared PAIR B.)
3. `segregation_priority_18_beats_subsidy_exhaustion_priority_38` — **business_safety (p18 `ERR_SEGREGATION_OF_DUTIES`) vs business_fiscal (p38)**. Approve issued as `committee-alice`, who authored SUBMITTED reviews, while the pool is 950000 short → 403 `ERR_SEGREGATION_OF_DUTIES`.

**`boundary_precision_check`** (2 instances, different metrics, distinct endpoints):
1. `subsidy_available_one_cent_below_versus_exactly_equal_to_silent_second` — metric: **money threshold `>=` on `subsidy_available_cents`**; endpoint `POST /homeownership/mortgage-applications/{id}/approve`. Both probes in one recipe: 1949999 → 409, one-cent `TOP_UP` → 1950000 → APPROVED, available lands on exactly 0 and posture flips to `SUBSIDY_RESTRICTED`.
2. `willingness_review_set_two_then_one_then_empty_collection_edge` — metric: **cardinality of the effective WILLINGNESS review collection (2 → 1 → 0)**; endpoint `POST /homeownership/selection-reviews/{id}/retract`. 80.0 → 90.0 → `null` (not 0, not a division error), then quorum drops below 2 so `selection-decision` returns 409 `ERR_COMMITTEE_QUORUM_NOT_MET`.

**`cross_entity_state_dependency`** (2 instances, different entity pairs):
1. `mortgage_close_blocked_until_build_site_leaves_safety_hold_and_completes` — **MortgageApplication → BuildSite**. `CLEARED_TO_CLOSE → CLOSED` preconditions quoted verbatim; site held at SAFETY_HOLD → 409 `ERR_SITE_NOT_COMPLETED`; release → UNDER_CONSTRUCTION → FINAL_INSPECTION → COMPLETED → same close succeeds, ledger moves 1950000 committed→disbursed, available 3050000.
2. `household_screening_blocked_while_parent_program_posture_is_frozen` — **ApplicantHousehold → AffiliateProgram**. `SUBMITTED → SCREENING` preconditions quoted verbatim (`"AffiliateProgram.program_posture != FROZEN"`); SUSPEND → 409 `ERR_PROGRAM_FROZEN`, RESUME → identical screen call writes PRELIMINARY need 100 / ability 100 / ami_pct 0.6.

## Verification run

- `yaml.safe_load` on `scaffold_difficulty_design:` + fragment: **PARSE OK**, 3 rules, instance names as listed.
- Concatenated with the real `SCAFFOLD_DIFFICULTY_DESIGN.yaml` in `/tmp`: **PARSE OK**, 7 rules / 17 instances, **zero duplicate `name` values**.
- Programmatic checks against `SCAFFOLD.yaml`, all empty: unresolvable `grounds` paths **0**; unknown `call:` endpoints **0**; payload fields not in the endpoint's declared `input:` **0**; `${var}` bound before use (setup → trigger → assert) **0 unbound**; `captures:` JSONPaths not present on the endpoint's declared `output:` entity **0**.
- Arithmetic pre-computed by hand and re-checked: escrow 15625+5000=20625, PI 75000−20625=54375, 240-month tier selected because 54375×360=19575000 ≥ 0.90×15000000, first mortgage 13050000, silent second 1950000; `ceil(0.60 × 1) = 1` so one confirmed general locks the shift; education `expires_on` 2028-07-31 (730 days from 2026-08-01, crossing leap day 2028-02-29).

## SCAFFOLD.yaml inconsistencies routed around (not fixed)

1. **Declared PRIORITY CONFLICT PAIR C (p20 `ERR_MEMBER_NOT_ACTIVE` vs p24 `ERR_FAMILY_CREDIT_CAP_REACHED`) is unreachable.** `HouseholdMember` only becomes REMOVED via the DENIED/WITHDRAWN cascade, DENIED is reachable only from COMMITTEE_REVIEW, and exhausting `family_member_credited_hours` requires prior CREDITED entries, which require `selection_status IN {SELECTED, PARTNERSHIP_ACTIVE}` — a state from which there is no path back to COMMITTEE_REVIEW. Routed around by substituting a third *reachable* pair with an equally distinct category pairing (p18 business_safety vs p38 business_fiscal).
2. **`errors.ERR_SITE_NOT_COMPLETED.condition`** says the error fires when readiness is "neither UNDER_CONSTRUCTION nor COMPLETED", contradicting §1.2 and §1.4 p37 which both require `== COMPLETED`. Routed around by staging the negative probe at readiness **SAFETY_HOLD**, which errors under both readings, instead of UNDER_CONSTRUCTION.
3. **`ERR_CHECK_IN_WINDOW_CLOSED`** says 60 minutes before `start_at` while §1.2/§1.4 p32 say 30. Avoided: no instance uses the check-in window as a boundary or a gate.
4. **`ERR_SHIFT_HAS_NO_SLOTS`** condition conflicts with the §1.2 open precondition on zero-slot shifts, making a `volunteer_slots == 0` / `fill_ratio == 0` edge unreachable. Chose the WILLINGNESS empty-collection edge as the zero-quantity boundary instead.
5. **`POST /homeownership/grant-awards`** declares `donor_name` / `amount_cents` while `entities.GrantAward.fields` declare `funder_name` / `award_amount_cents`. Avoided: no instance touches grant awards or the impact report.
6. **`POST .../lien-actions`** §1.5 action names (FORBEARANCE/CURE/TRANSFER_NOTICE/RECAPTURE/PAYOFF) differ from the §1.2 `lien_status` triggers. Avoided: no instance issues a lien action.
7. **`term_months`** is a declared `input:` on `POST /homeownership/mortgage-applications` although it is a computed field written by `affordable_payment_structure`. Followed the existing rule-4 precedent (pass `240`) and asserted the recomputed value from `submit-underwriting` separately.

### Subagent summary — rules 8–9 (verbatim)

Done. Fragment written and verified.

## Deliverable
`_frag_rules_8_9.yaml` — **291 lines**, two top-level list items at 2-space indent, no `scaffold_difficulty_design:` key.

| rule_id | instance names |
|---|---|
| `resource_temporal_overlap` | `overlap_site_closed_60min_cleanup_buffer_exact_abutment`, `overlap_volunteer_half_open_zero_buffer_back_to_back_allowed` |
| `compensating_invariant` | `invariant_subsidy_pool_approve_then_deny_restores_available_cents`, `invariant_sweat_equity_hours_credit_then_reverse_nets_to_zero` |

## How the "must differ" clauses are satisfied
- **Rule 8 / instance 1** — resource = **BuildSite**; geometry = **closed, symmetric 60-minute cleanup buffer** (`calculations.site_shift_buffer_overlap`). Probes the exact boundary against a held 08:00→12:00 shift: start at 13:00:00.000Z (gap of exactly 60 min) → **201 accepted**; start at 12:59:00.000Z (59 min) → **409 ERR_SITE_SHIFT_BUFFER_CONFLICT**.
- **Rule 8 / instance 2** — resource = **VolunteerProfile identity**; geometry = **half-open `[start, end)` with ZERO buffer, adjacency allowed** (`calculations.volunteer_shift_overlap_and_weekly_cap`), plus the Monday-anchored 40.00 h aggregate window. Seat starting exactly at the held shift's `end_at` (12:00:00.000Z) → **201, assigned_hours_committed 4.00→8.00**; seat starting 11:59:00.000Z → **409 ERR_VOLUNTEER_DOUBLE_BOOKED**, committed stays 8.00. Three build sites are used deliberately, because the site rule's buffer makes back-to-back shifts impossible on one site.
- **Rule 9 / instance 1** — conserved quantity is **monetary**: `subsidy_pool_cents == available + committed + disbursed` on a 20 000 000-cent pool. Before 20 000 000 / 0 / 0 → approve → **mid 18 050 000 / 1 950 000 / 0** → deny → after 20 000 000 / 0 / 0. Silent second pre-computed through the pinned 8-step formula: escrow 15 625 + 5 000 = 20 625; pi = floor(250 000×0.30) − 20 625 = 54 375; provisional 19 575 000 ≥ 13 500 000 → term 240; principal 13 050 000; silent second 1 950 000.
- **Rule 9 / instance 2** — conserved quantity is a **non-monetary hour counter**: `sweat_equity_credited_hours` / `HouseholdMember.credited_hours_to_date`. Before 0.00 → credit (weight 1.00, 6.00 h) → **mid 6.00** → reverse → after 0.00, with the original at +6.00 in REVERSED and the mirror at −6.00 in CREDITED summing to 0.00. `selection_status` stays PARTNERSHIP_ACTIVE, proving the compensation is scoped to the counter.

## Verification
- YAML parse of `scaffold_difficulty_design:` header + fragment: **PASS**.
- `scaffold_lint.py` on a temp task dir (frozen SCAFFOLD.yaml copy + header-prefixed fragment): **`VERDICT: clean lint`** — 87 calls scanned, 4 instances, all §1.5 conformant (path/method/role/`payload ⊆ input`/`captures ⊆ output`/OCC-`${var}`).
- Scripted placeholder-closure + allowed-key check: **PASS**, zero unbound `${var}` (including in `assert:`), no name collisions with the 10 existing instances.
- Every OCC input is a `${var}` re-read immediately before the guarded call (`GET /construction-shifts/{id}` → `expected_shift_version`; `GET /households/{id}` → `expected_household_version`; `GET /programs/{id}` → `expected_program_version`).
- Segregation of duties honored: officer-1 structures / officer-2 approves and denies; reviewers are only committee-alice/committee-bruno; the hour entry is claimed by fsc-1 and verified by cm-1.

## SCAFFOLD.yaml inconsistencies routed around (no edits made)
1. **`ERR_SITE_NOT_READY_TO_BUILD` vs validation priority 26** — the error condition says a shift may not be "scheduled *or* opened" on a non-ready site, but p26's `applies_to` covers only `POST /construction-shifts/{id}/open`. Routed around by advancing every site to `READY_TO_BUILD` (TITLE → ENVIRONMENTAL → UTILITIES) before any shift creation, so both readings pass.
2. **`ERR_WORK_DATE_OUT_OF_RANGE` lower bound** — p21 says `work_date >= ApplicantHousehold.created_at`, §1.6 says "strictly before the household's selection_status first reached SELECTED". Routed around by advancing the clock to 2026-08-03 after the selection decision and using `work_date` 2026-08-02T09:00Z, which is after both anchors.
3. **Clock payload field naming** — p44 refers to `to_iso8601` while §1.5 declares `input: [current_utc]`. Used `current_utc` (matches §1.5 and the existing rules 1–4 instances).
4. **`POST /mortgage-applications` declares `term_months` as input** although §1.3 computes it at submit-underwriting. Passed the literal `240`, which equals the value the formula selects, so the chain cannot disagree with the computed structure.
5. **`BuildSite.assigned_household_id`** is documented in §1.1 as a side effect of `POST /mortgage-applications` but is absent from that endpoint's `side_effects:` list; the assertion (`null` after the deny) is consistent with both readings.

### Orchestrator post-verification

Concatenated file re-parses under `yaml.safe_load` with exactly one top-level key `scaffold_difficulty_design`. Per-rule instance counts: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2. All nine §0.5 `rule_id`s present, no extras, and every rule meets its ≥2-instance floor.

## Step 4: Generate PRD — 2026-09-01T04:06:00.000Z

Launched concurrently with Step 2b: PRD generation reads only `SCAFFOLD.yaml` (already valid at resume time) and both design indices are withheld from it by contract, so it carried no dependency on Step 2b's completion.

Subagent summary (verbatim):

PRD generation is complete.

**Output:** `workspace/PRD.md` — 484 lines, 26 headings, ends at §5 as required.

**Structure delivered**
- §1 Introduction (3 paragraphs).
- §2 Global specifications, 11 subsections: RBAC over `X-User-ID`/`X-User-Role` for the 7 roles (5 opaque, 2 entity-backed); §2.2 copied verbatim from `section-2.2-response-structure.md`; pagination and list ordering with every filter enumerated; identity/versioning/404 resolution order; the logical clock (starting `2026-08-01T00:00:00Z`) and its cascades; money/hours/rounding discipline (integer cents, floor vs. half-up pinned, per-entry-then-sum rounding pinned, 4dp ratios); the four optimistic-concurrency rules → HTTP 412; the full ordered rejection ladder covering all 44 validation rows plus the three priority-conflict pairs; segregation of duties; the subsidy pool as a conserved quantity with `program_posture` derivation; two-dimensional state and cascade discipline.
- §3 Business logic, 9 workflow subsections: program/subsidy stewardship, intake and screening with both scoring variants, committee scoring + selection fork + deterministic waitlist selector, the sweat-equity hour ledger with its six-step waterfall and ledger invariant, education and closing readiness, land/readiness/safety-hold/cost capture with both cost bases, volunteer scheduling and attendance with the seat and weekly-cap invariants, mortgage origination through the pinned eight-step affordability structure to closing, and lien life (forgiveness, ROFR, recapture tiers, payoff) plus grant impact reporting.
- §4 endpoint table: exactly 71 rows, exactly 4 columns.
- §5 error catalogue: exactly 71 rows, exactly 2 columns.

**Hard Contract results**
1. Field-Name Coverage — **PASS.** 171 names harvested from every entity `fields:` declaration and every endpoint `input:` list (optional `?` markers stripped): 0 missing from backticked PRD text. A broader sweep of all snake_case identifiers in the scaffold left only 14 residuals, all of which are formula intermediates described in prose (cost burden ratio, DTI, appreciation, recapture total, shared percentage, weekly hours, age at work date, the two basis selectors) or scaffold metadata keys (`rule_id`, `http_status`) — none are request or response field names.
2. Rule Coverage — **PASS.** All 71 error ids appear in §1–§3 prose, not only in the §5 table. All 48 distinct state values across the 9 state-machine dimensions appear, as do all `action ==` enum values. All 14 calculations, all 62 transitions with both branches of every fork, all cascade hops, and all field defaults are stated explicitly.
3. §3 Path Purity — **PASS.** 0 backticked tokens in §3 begin with `/`, are a bare HTTP method, or combine method with path.

**Scaffold contradictions resolved** (validations table and state machines treated as primary over error-catalog prose): check-in window 30 minutes (not 60); trade seats capped at `required_trade_slots + 2` and general seats at `volunteer_slots`; closing requires an already-`COMPLETED` site rather than moving the site itself; impact reporting permitted once the clock reaches `period_end` inclusive; the `right_of_first_refusal_expires_on` window pinned to 30 days after the action's `effective_date` with a note that operators stamp it at the current logical instant, reconciling the two sources. Two naming divergences were surfaced as accepted aliases so either spelling satisfies a test: the five lien actions (`FORBEARANCE_GRANT`/`FORBEARANCE`, `REINSTATE`/`CURE`, `TRANSFER_REQUEST`/`TRANSFER_NOTICE`, `RECORD_TRANSFER`/`RECAPTURE`, `SATISFY`/`PAYOFF`) and the grant award's `donor_name`/`funder_name` and `amount_cents`/`award_amount_cents` pairs.

No `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `_frag_rules_*.yaml`, or sibling `task_*/` directory was opened, grepped, or referenced at any point. No contract report text was written into PRD.md or any sibling file.

### Orchestrator post-verification

`workspace/PRD.md` is 483 lines with 28 markdown headings and terminates on the final row of the §5 error table (`ERR_CLOCK_MUST_ADVANCE | 422`) — complete, not truncated.

## Step 2c: Generate SCAFFOLD_CORNER_DESIGN.yaml — 2026-09-01T05:40:00.000Z

Run after Step 2b completed, because §1.9's `excluded_because.difficulty_instance` citations must resolve against the finished §1.8 instance list. Fragment files `_frag_rules_5_7.yaml` / `_frag_rules_8_9.yaml` deleted after their contents were merged.

Subagent summary (verbatim):

§1.9 corner design for task 2213 is complete and lint-clean.

**Deliverable:** `SCAFFOLD_CORNER_DESIGN.yaml` — **2862 lines**, single top-level key `scaffold_corner_design:`, parses under `yaml.safe_load`.

**Instances: 92 total — 77 fully worked, 15 `excluded_because` stubs.**

| `section:` | instances | stubs | guide rows deliberately skipped |
|---|---|---|---|
| entities | 14 | 0 | none applicable (topology row `flat` covered by the FK / reverse-reachability pair; `hierarchical`/`graph`/`hybrid` not declared) |
| state_machines | 17 | 3 | shape rows `linear`/`cyclic`/`parallel`/`compound` (shape is `branching`); side-effect row **Bubble up** (no machine derives a parent state from all-children-terminal) |
| calculations | 13 | 2 | algorithm rows `forward_looking`, `chronological`, `tiered_pricing`, `topological`, `projection` — no calculation declares them (declared set: weighted_scoring, aggregation, waterfall_allocation, constraint_propagation, threshold, interval_merge, decay_function) |
| validations | 31 | 7 | none — all six pattern rows covered; declared PAIR C (p20 vs p24) not attempted, state-unreachable |
| endpoints | 4 | 0 | **Cross-reference link** — flat topology has no junction entity; FK-link semantics live in the entities section |
| errors | 1 | 0 | — (audit-style, see below) |
| rbac | 4 | 1 | role_model rows `approval_chain`, `peer_roles`, `hierarchical_override`, `delegated_authority` (model is `segregation_of_duties`) |
| cross_cutting_complexity_layers | 6 | 2 | all nine undeclared layers; `selector_policy` is not a guide row |
| consistency_model | 2 | 0 | `eventual`, `saga` (model is `immediate`) |

**Verdict line, verbatim:**
`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`
(with `§1.9 instances scanned: 77`, `Calls scanned (§1.8+§1.9): 1859`)

**Other checks, all green:** grounds resolvability `BAD GROUNDS: 0`; zero duplicate names; zero collisions with the 21 §1.8 names; zero bad `difficulty_instance` citations; zero unbound `${…}` placeholders across 1383 calls; every call carries `as`/`as_user_id`.

**Coverage across §1.8 ∪ §1.9:** endpoints **71/71** (corner file alone 69); error ids **71/71 referenced**, of which **68 are actively triggered** — `ERR_EDUCATION_NOT_COMPLETE`, `ERR_EDUCATION_EXPIRED`, `ERR_SWEAT_EQUITY_INCOMPLETE` appear only in `setup_note`s documenting them as unreachable by construction (their sole site is `/close`, which requires `CLEARED_TO_CLOSE`; the `APPROVED -> CLEARED_TO_CLOSE` guard withholds that status from exactly the cases they describe, so p10 `ERR_TRANSITION_NOT_ALLOWED` always pre-empts). The `errors` section is therefore an envelope/triggerability audit (one probe per HTTP class: 401/403/404/409/412/422, all asserted to share `response_type: error` + `data` with exactly `error_id` and `message`) rather than a hunt for §1.6-only ids — every one of the 71 ids has a §1.4 row.

**Inconsistencies routed around (no scaffold edits):**
- *dual-reading staging (holds under both readings):* `ERR_SHIFT_HAS_NO_SLOTS` staged with `volunteer_slots 0` **and** `required_trade_slots 0`; `ERR_CHECK_IN_WINDOW_CLOSED` staged four days early (violates both the 30- and 60-minute wording; PRD pinned 30); `ERR_SITE_NOT_COMPLETED` staged at `SAFETY_HOLD`; `ERR_WORK_DATE_OUT_OF_RANGE` staged with `created_at == SELECTED` instant so the accepted claim clears both lower bounds; `ERR_ROFR_WINDOW_OPEN` staged mid-window.
- *spelling picks:* GrantAward sent with the §1.5 input names `donor_name`/`amount_cents` and asserted on **values** so it holds under the §1.1 `funder_name`/`award_amount_cents` spelling (documented in a `setup_note`); lien-actions use the §1.5 enum (FORBEARANCE/CURE/TRANSFER_NOTICE/RECAPTURE/PAYOFF); clock payload field `current_utc`; `term_months` passed as the literal the formula selects (240).
- *corner substitution (new this session):* `POST /build-sites/{id}/readiness-advance` declares roles `[ProgramAdmin, ConstructionManager]` while the three clearance transitions name `actor: ProgramAdmin` only — so the rbac shared-operation probe was moved onto `POST /volunteers` and `POST /cost-entries`, which have no state machine and hence no competing `actor:` clause (`setup_note` records why).
- *single-reading staging (disclosed):* `a_shift_cannot_open_on_a_site_short_of_utilities_clearance` fires only on `/open`, p26's sole `applies_to` endpoint, so §1.6's "scheduled or opened" wording is not probed at schedule time.
- *not attempted / unreachable:* PAIR C (p20 vs p24); the DENIED half of `ERR_VETO_REASON_REQUIRED` (selection-decision input is only `decision_minutes`); the REMOVED-member half of `ERR_MEMBER_NOT_ACTIVE` (no endpoint moves `HouseholdMember.status`); a repeat impact report on a REPORTED award (no §1.4 row, no state machine, no derivable id).
- *resolved non-inconsistency:* §1.2's forbearance note ("the third grant is refused") agrees with p41's `<= 1`; no hedge needed.

Frozen files were not modified; no violations were found in them.

## Step 6: Generate implementation — 2026-09-01T05:41:00.000Z

Launched concurrently with Step 2c. Physical isolation from Step 5 was preserved by construction: `test_suite/` and `test_helpers/` did not exist on disk at any point during this subagent's lifetime, so the implementation could not have read them even had it tried.

Subagent summary (verbatim):

Done. The implementation is complete and verified.

## What was built

`workspace/implementation/` — 22 Python modules plus `start.sh` and `requirements.txt`:

- **Infrastructure**: `util.py` (Decimal/rounding/ISO-8601/date math), `errors.py` (71-entry error-id → HTTP status map), `store.py` (in-memory dicts, logical clock, `stamp`/`touch`/`bump` with once-per-request versioning), `envelope.py`, `payload.py` (validators with alias support), `rbac.py` (7 roles, 2 entity-backed), `derive.py` (all `source: computed` fields + JSON projection), `calc.py` (14 calculations), `cascade.py` (state gates + cross-entity cascades), `common.py`, `app.py`.
- **Routes** (one blueprint per domain): `r_program`, `r_household`, `r_review`, `r_sweat`, `r_site`, `r_shift`, `r_assignment`, `r_education`, `r_mortgage`, `r_grant`, `r_clock`.

## Verification results

- `python3 -m py_compile *.py` → clean.
- **Endpoint coverage: 71 spec endpoints, 71 implemented, 0 missing, 0 extra.** No endpoint was left unimplemented.
- **Fresh-boot / no-seed**: each `PORT=<n> bash start.sh` boots in the foreground on `0.0.0.0`, and a brand-new process reports `total_count: 0` on every collection with the clock back at `2026-08-01T00:00:00.000Z`. Storage is plain dicts only; nothing touches disk.
- **Full lifecycle smoke test: FAILURES 0.** Program → household + members → submit → screen → referral → 9 committee reviews → selection (composite 93.5, required 300 h) → build site readiness → cost entries (cash + in-kind + void) → sweat equity claim/verify/credit → volunteers → shift open/assign/confirm/lock/check-in/complete (incl. NO_SHOW strike) → education modules → mortgage create/preview/underwrite (`escrow 40000 / pi 59999 / term 300 / first 17999700 / silent 12000300`) → approve (auto-continue to `CLEARED_TO_CLOSE`) → close → 20-year forgiveness → payoff → grant + impact report.
- **Error-path test: 41 of 43 assertions passed; the 2 "failures" were wrong expectations in my test, not implementation bugs** — PRD §2.6 pins `ERR_UNKNOWN_ROLE` at **401** (not 400) and puts the role-authorization check (step 3) *before* identity resolution (step 4), so `GET /homeownership/households` as `Applicant` correctly returns `ERR_ROLE_NOT_PERMITTED` (that endpoint's role list excludes `Applicant`). Confirmed separately that `GET /homeownership/households/{id}` as `Applicant` with an unknown id yields `403 ERR_IDENTITY_NOT_FOUND`.
- Verified live: 401/403/404/405/412/422 shapes, pagination bound rejections, `ERR_STALE_PROGRAM_VERSION` (412), body-FK resolution order, `ERR_PROGRAM_FROZEN` winning over `ERR_DOCUMENTATION_INCOMPLETE`, `ERR_POOL_BELOW_OBLIGATIONS`, in-kind mismatch, `ERR_SHIFT_HAS_NO_SLOTS` / `ERR_REQUIRED_TRADE_MISSING`, and the ±60-minute site buffer geometry (59 min collides, exactly 60 min accepted).
- **Recapture path test: FAILURES 0.** `TRANSFER_NOTICE` → `TRANSFER_PENDING` with `right_of_first_refusal_expires_on` at +30 days; `RECORD_TRANSFER` inside the window refused with `ERR_ROFR_WINDOW_OPEN`; after the window, recapture at 75 % of 10,000,000 appreciation pushed the pool 100,000,000 → 107,500,000 with disbursed dropping to 0, and the frozen lien figures stop recomputing once `RECAPTURED` (per PRD §3.9). All five lien-action aliases exercised live (`FORBEARANCE`, `CURE`, `TRANSFER_NOTICE`, `RECAPTURE`, `PAYOFF`), as were the grant aliases `donor_name` / `amount_cents`.

## Bugs found and fixed during verification

1. `r_assignment.py` used a nonexistent error id `ERR_VERSION_CONFLICT` → corrected to `ERR_STALE_SHIFT_VERSION` (412).
2. `rbac.Actor` lacked the `entity_id` property that `r_assignment.py` called.
3. Validation ladder in `create_assignment` had weekly cap (priority 31) firing before seat inventory (priority 30) — reordered to 28 → 29 → 30 → 31.
4. `sale_price_cents`, `recapture_total_cents`, `shared_appreciation_cents` were leaking as undeclared response fields on `MortgageApplication` → renamed to underscore-prefixed internals so `derive.project()` strips them.
5. `r_household.read_member` had a missing `get_member` import (guaranteed `NameError`).
6. The impact report serialized `sweat_equity_hours` as the JSON **string** `"308.00"` because that payload never passed through the Decimal converter → added `derive.jsonable()` and routed the report through it; now emits `308.0`.

## Judgement calls where the specs were ambiguous (all resolved toward PRD.md)

- Terminal-state check precedes legal-origin check in `cascade.state_gate()`, otherwise `ERR_ALREADY_TERMINAL` would be unreachable.
- NO_SHOW seats **leave** `assigned_hours_committed` (both the scaffold invariant formula and PRD §3.7's conserved-quantity sentence enumerate only `RESERVED|CONFIRMED|CHECKED_IN|COMPLETED`); the seat still records a strike.
- Unnamed preconditions map to `ERR_TRANSITION_NOT_ALLOWED`; `ERR_HOUSEHOLD_NOT_SELECTED` is used only where the PRD names it.
- The site-readiness gate on `submit-underwriting` uses `ERR_SITE_NOT_READY_TO_BUILD` (priority 35 names only two error ids, neither of which fits).
- Subsidy `disbursed` stays fully derived per §2.10, so a lien reaching `SATISFIED`/`RECAPTURED` drops out of that bucket entirely.

## Step 5: Generate unit tests — 2026-09-01T07:35:00.000Z

Run after Step 2c, since queue B requires the completed §1.9 index. `workspace/implementation/` already existed at this point but was withheld from the subagent by explicit prohibition; the test suite derives from the two design indices plus PRD prose only.

Subagent summary (verbatim):

The suite is complete.

## What was emitted

- **`test_helpers/`** — 9 modules: `__init__.py`, `types.py`, `api_client.py` (`HomeownershipClient`, one method per endpoint), `api_errors.py` (all 71 ids), `assertions.py` (envelope/pagination/pool-identity/two-dimension/committed-hours helpers), `factories.py`, `constants.py`, `test_users.py` (fixed opaque ids + `make_applicant_headers`/`make_volunteer_headers` minting entity-backed identities from server ids), `fixtures.py` (state-machine builders, all reachable from an empty database).
- **`test_suite/`** — `conftest.py` plus **14 test files, 119 test functions**: `test_01_selection_scoring` (11), `test_02_sweat_equity` (14), `test_03_sites_and_costs` (5), `test_04_shifts` (15), `test_05_assignments` (9), `test_06_education` (2), `test_07_underwriting` (8), `test_08_approval_and_closing` (12), `test_09_liens_and_grants` (8), `test_10_program_and_waitlist` (13), `test_11_envelope_and_defaults` (8), `test_12_reads_and_references` (5), `test_13_clock_errors_and_rbac` (5), `test_14_concurrency` (4).

## Design-index mapping (verified mechanically)

A script re-parsed both design files and every emitted `Design:` line:

- Queue A (Difficulty): **21/21 instances covered**, 0 missing.
- Queue B (Corner): 92 instances = 15 `excluded_because` stubs + **77 worked, 77/77 covered**, 0 missing.
- 98 distinct tags across 119 tests; **0 dangling tags**, **0 tags pointing at a stub**, every test carries **exactly one** `Design:` line and it is the last line of its docstring.
- **No instance was skipped** — the PRD-first two-condition filter admitted all 98 worked instances (individual sub-assertions were narrowed where noted below, but no instance lost its test).

## Verification

- `python3 -m py_compile` clean on all 23 generated `.py` files.
- `python3 -m pytest test_suite/ --collect-only -q` → **119 tests collected**, no import or collection errors (no server running).
- No `skip`/`xfail`/marker usage; no comment anywhere mentions the design documents' provenance; `__pycache__` removed.

## Design-index defects routed around

1. **Non-v4 probe UUID** (instances at corner lines 228/253/278): the design literal `00000000-0000-0000-0000-0000000009ff` is well-formed but not version 4, so a strict validator could reject it at priority 8 before the priority 5/6 not-found check runs. Normalized to `C.PROBE_UUID = "00000000-0000-4000-8000-0000000009ff"`.
2. **`advocacy_category_allowance_fills_then_refuses_the_next_entry`** asserts `hours_credited == 0` on a refused entry where the PRD leaves it null; asserted `status == VERIFIED` and the capped figure instead.
3. **`minor_multiplier…`** names the member field `credited_hours`; the PRD says `credited_hours_to_date` — used the PRD spelling.
4. **Forgiveness-curve date arithmetic slip**: the design's 2031-06-06/2031-07-06/2031-08-05/2046-04-18 are months 58/59/60/239, not 59/60/61/240; substituted 2031-06-10/2031-07-10/2031-08-09/2046-04-22.
5. **Lien "recapture total"** is not a stored field; only response fields asserted.
6. **Grant-award aliasing** (`donor_name`/`funder_name`, `amount_cents`/`award_amount_cents`): read by value through `_award_money`/`_award_funder` so either declared spelling passes.
7. **Willingness-cardinality mid-state composite** assertion dropped as not uniquely derivable from the PRD (the rest of that instance is asserted).
8. **Clock response field name** is not pinned by the PRD ("The endpoint returns the clock state"), so the accepted one-millisecond step is verified by the `created_at` of the next write rather than by guessing a response key.
9. **Shift check-in window**: PRD says 30 minutes, the scaffold error catalogue says 60. Followed the PRD; the affected design instances hold under both readings.
10. Index-acknowledged unreachable errors (`ERR_EDUCATION_NOT_COMPLETE`, `ERR_EDUCATION_EXPIRED`, `ERR_SWEAT_EQUITY_INCOMPLETE`, half of `ERR_VETO_REASON_REQUIRED`, the REMOVED half of `ERR_MEMBER_NOT_ACTIVE`) are documented as unreachable by the design itself and get no test.

The implementation directory and all sibling tasks were never read.

## Step 7: Run tests and iterate — 2026-09-01T07:30:00.000Z

Subagent summary (verbatim):

Clean sweep achieved.

## Summary

**Iterations run:** 2 (each = 8 concurrent full rounds, `per-test-server` isolation, no early exit).
- Iteration 1: 113/119 in all 8 rounds — 6 failures, identical in every round (no flakiness signal).
- Iteration 2: **119/119 in all 8 rounds.**

**Tests deleted:** none. All 6 failures were test-layer defects repairable under STEP 2 / STEP 1c partial-coverage splitting.

**Fixes applied to `test_helpers/`:** none. `api_errors.py`'s status map was verified correct against PRD §5 row-for-row; fixtures, factories and the role-header builders (`test_users.py`) were traced end-to-end and found faithful (entity-backed `Applicant`/`Volunteer` ids are server-minted; SoD identities `officer-1` != `officer-2`, claimant `fsc-1` != verifier `cm-1`, committee != decider).

**Fixes applied to `test_suite/` (assertion mis-translations of PRD):**
- `test_01_selection_scoring.py::test_the_income_band_accepts_both_bounds_and_refuses_one_cent_of_slack` — dropped `ami_pct == 0.3` / `== 0.8` on the referral response. PRD §3.2 says the referral *gates* on "final-basis `ami_pct`" but names the final basis as used for "the income-band gate at committee referral, and **the recomputation** at the selection decision" — only the decision recomputes/writes. The sibling passing test asserts `ami_pct == 0.6` and `score_basis == PRELIMINARY` *after* referral, so the deleted assertions were self-contradictory within the suite. Boundary coverage retained (both bounds admit → `COMMITTEE_REVIEW`; 0.8333 → `ERR_INCOME_OUT_OF_BAND` 422).
- `test_02_sweat_equity.py::test_the_identity_that_claimed_an_entry_cannot_verify_it` — expected status corrected 409 → **403**. PRD §5 and §2.8 item 19 both put `ERR_SELF_VERIFICATION_FORBIDDEN` at 403. Exact `error_id` assertion untouched.
- `test_04_shifts.py::test_the_synthesized_partner_entry_arrives_verified_but_not_yet_credited` — `entry["household_member_id"]` → `entry["member_id"]`. PRD §3.4 names the sweat-equity entry's field `member_id` (also the declared list filter); `household_member_id` is the *assignment*'s field.
- `test_04_shifts.py::test_a_lock_is_refused_while_the_named_trade_seat_is_empty` — `safety_briefing_reference` (input-echo silence: PRD names it only as a lock request field, never as a shift attribute; the shift's field enumeration lists `safety_briefing_completed`) replaced with the PRD-verbatim `safety_briefing_completed` False-before / True-after-lock assertions, which is a strictly stronger PRD-traceable check.
- `test_05_assignments.py::test_the_third_no_show_suspends_the_profile_and_bars_the_next_seat` — dropped the incidental `assigned_hours_committed == 3.0` after the first no-show. PRD §3.7 self-conflicts here: the conserved-quantity formula ("equals the sum of `duration_hours` over that volunteer's seats in `RESERVED`, `CONFIRMED`, `CHECKED_IN`, or `COMPLETED` status" — `NO_SHOW` absent ⇒ 2.0) versus "A no-show is deliberately *not* compensating: the hours stay committed" (⇒ 3.0). Both readings are verbatim, so the outcome is not uniquely derivable. The test's own design rule (three no-shows ⇒ 3 strikes ⇒ `SUSPENDED` ⇒ next seat refused `ERR_VOLUNTEER_SUSPENDED` 422, first seat terminal `NO_SHOW` with null `checked_in_at`) is fully retained.
- `test_13_clock_errors_and_rbac.py::test_an_entity_backed_identity_must_resolve_and_may_only_address_its_own_seat` — dropped `released["cancellation_reason"] == ...`. Input-echo silence: PRD names `cancellation_reason` only as a seat-release request field, never as an assignment attribute. `ERR_IDENTITY_NOT_FOUND` → `ERR_NOT_RESOURCE_OWNER` ordering and the `CANCELLED` outcome are retained. (This was the suite's only echoed-input assertion; no consistency precedent was broken.)

**Fixes applied to `workspace/implementation/`:** none required. Every failure traced to the test layer; no PRD-required check was weakened, no endpoint/field/side-effect was added, and storage remains in-memory dicts only (verified: no SQLite/JSON/`/tmp` persistence, no startup seeding), so `start.sh` re-invocation wipes all state.

### Orchestrator post-verification

All 8 `results.{1..8}.json` in `workspace/implementation/` report `119 / 119`. Step 8 is NOT skipped: although `implementation/` needed zero fixes, the run took 2 iterations and produced 6 `test_suite/` fixes, and several of those trace to genuine PRD under-determination (the §3.7 no-show conserved-quantity self-conflict, the §3.2 final-basis recomputation timing, and two input-echo silences) that Step 8 must pin against the implementation.

## Step 8: Finalize PRD — 2026-09-01T07:40:00.000Z

Not skipped: Step 7 took 2 iterations and produced 6 `test_suite/` fixes. Because Step 7 applied zero `implementation/` fixes, the subagent was told explicitly that "no PRD change needed, test-authoring slip" is a valid per-item verdict, so that pure assertion slips would not be mistaken for PRD silences.

Subagent summary (verbatim):

Done. `PRD_FINALIZED.md` written with 4 inline edits on 3 lines.

## Size delta
- **Lines:** PRD.md 483 → PRD_FINALIZED.md 483 (**0.0%**; every edit is inline inside an existing long paragraph line).
- Words 14,945 → 15,157 (**+1.42%**); bytes 109,942 → 111,319 (**+1.25%**).
- Changed lines: 203, 279, 293 only.

## Changes
- **§3.2 (final basis)** — *insert* — after "…the recomputation at the selection decision.", pinned that only the selection decision writes a final-basis figure; the committee referral computes final-basis `ami_pct` for its gate alone and leaves stored `ami_pct` / `need_score` / `ability_to_pay_score` / `score_basis` at their preliminary values — `r_household.py:192-197` (inline gate-only computation) vs. `calc.py:94-107` reached only from `r_household.py:172` and `:242`.
- **§3.7 (lock)** — *insert* — `safety_briefing_reference` is a request field only: presence-checked, then discarded; never stored on the shift, never echoed; briefing state is `safety_briefing_completed` alone — `r_shift.py:167,175-176,187` and shift row literal `r_shift.py:79-93`.
- **§3.7 (cancellation)** — *insert* — `cancellation_reason` on both shift-cancel and seat-release is request-only, never stored/echoed — `r_shift.py:285`, `r_assignment.py:256`; assignment row literal `r_assignment.py:122-129`.
- **§3.7 (committed hours)** — *revise* — replaced "A no-show is deliberately *not* compensating: the hours stay committed…" with: a no-show releases the hours exactly as a cancellation does (`NO_SHOW` is not a held status) but leaves a permanent strike; added that the four-status formula governs universally — `derive.py:209-220` (`HELD_SEAT_STATUSES` excludes `NO_SHOW`), `r_shift.py:234-243`.

## Per-edit pre-edit search log
1. **Edit A — subject: who writes `ami_pct` / `need_score` / `ability_to_pay_score` / `score_basis`.** Enumerated: `calc.score_household` (calc.py:94-108) and its only two callsites (`r_household.py:172` screen/PRELIMINARY, `:242` decision/FINAL); `create_household` initialisers (r_household.py:79-85); `refer_household` (r_household.py:178-204 — writes none of them); `return_to_screening` (r_household.py:218-222 — clears composite/willingness, resets `score_basis`, leaves the other three); `r_review.refresh_committee_figures` (r_review.py:21-30 — writes only `willingness_score`/`composite`); grepped `r_program.py`, `r_mortgage.py`, `r_grant.py`, `r_sweat.py`, `cascade.py` for all five field names (no hits, so waitlist promotion and every cascade leave them alone). (c) Adjustment: scoped the claim to *the referral* and phrased the carried-forward value as "whatever the last preliminary pass wrote" rather than naming fixed values, so the `COMMITTEE_REVIEW → SCREENING → COMMITTEE_REVIEW` loop (which resets `score_basis` without touching the other three) stays correctly described.
2. **Edit B — subject: the shift entity's persisted/response-visible field set.** Enumerated: `r_shift.py:79-93` (creation), every `shift["…"] = ` write in the codebase (grepped: cascade.py:165, derive.py:199-205, r_shift.py:154,156,186,187,218,291), `derive.refresh_shift`, `derive.project` (emits only non-underscore row keys), `r_shift.py:167` (validated local `reference`, used only at :175), `r_assignment.py:234` (check-in reads `safety_briefing_completed`), `r_shift.py:154` (reopen resets it to false). (c) No adjustment needed; the claim is confined to the reference field and explicitly leaves `safety_briefing_completed` as the state carrier, matching both the lock and reopen paths.
3. **Edit C — subject: the assignment entity's persisted/response-visible field set, plus shift-cancel.** Enumerated: `r_assignment.py:122-129` (creation) and every `seat[…]/assignment[…]` write (cascade.py:145, r_shift.py:224,235, r_assignment.py:215,242,243); `cascade.release_seat`/`cancel_shift_seats`/`safety_hold_cascade`/`suspend_volunteer_cascade` (none add keys); both `cancellation_reason` validation sites (r_shift.py:285, r_assignment.py:256); `derive.public_assignment`/`project`. (c) Adjustment: wrote "never stored on the shift **or** on the assignment" to cover both request sites, and deliberately said nothing about which origin states a release is legal from, so the existing state list in that sentence is untouched.
4. **Edit D — subject: `assigned_hours_committed` and the `NO_SHOW` seat status.** Enumerated: `derive.refresh_volunteer` (derive.py:209-220, sole authority; also derives `no_show_strikes` as a count of `NO_SHOW` seats), the only stored initialiser (`r_shift.py:336`, 0.00), every refresh callsite (r_assignment.py:136 reserve, r_shift.py:232/241 complete, cascade.py:151 release_seat, cascade.py:172 suspend cascade), `derive.public_volunteer` (recomputes on every read, incl. list), all four `NO_SHOW` references (grepped: only set at `r_shift.py:235`, i.e. shift close-out; terminal per `r_assignment.py:22`), plus the §3.6 safety-hold and §3.7 lock-release prose that the same formula must keep satisfying. (c) Adjustment: kept the existing formula sentence verbatim, tied the no-show statement to "recorded when the shift closes out" (the only producer of that status), and added an explicitly universal restatement of the formula so no exit path is left implicitly excluded.

## Verdicts on the 6 `<step_7_diff>` items
1. **`test_01` `ami_pct` on the referral response — PRD patched.** Genuine under-determination: §3.2 named the final basis as used at the referral gate *and* said the decision "recomputes", without saying whether the referral persists the recomputed figure. Impl (`r_household.py:192-197`) gates on a locally computed value and writes nothing, so `score_basis` stays `PRELIMINARY` and `ami_pct` stays preliminary after referral. Pinned.
2. **`test_02` self-verification 409 → 403 — no PRD change needed.** Pure test slip: PRD already states 403 in §2.8 item 19, §2.9 and the §5 catalogue, and `errors.py:10` maps it to 403.
3. **`test_04` `household_member_id` → `member_id` — no PRD change needed.** Pure test-authoring slip: PRD §3.4 and the §2.3 filter list already name the entry field `member_id` (`r_sweat.py:68`), while `household_member_id` is the assignment's field (`r_assignment.py:125`).
4. **`test_04` `safety_briefing_reference` — PRD patched.** Genuine silence: PRD named it only as a lock request field and never said whether it is persisted/echoed; impl validates and discards it. Pinned as request-only, with `safety_briefing_completed` named as the sole briefing-state field.
5. **`test_05` `assigned_hours_committed == 3.0` after a no-show — PRD patched.** Genuine self-conflict *and* a mismatch: the conserved-quantity formula (which impl implements verbatim in `derive.py:214-218`) excludes `NO_SHOW`, while the following sentence claimed "the hours stay committed". The false half was rewritten to match impl; the strike semantics were kept.
6. **`test_13` `cancellation_reason` on the released seat — PRD patched.** Same class of silence as item 4: named only as a request field, never stored (`r_assignment.py:256`, `r_shift.py:285`). Pinned as request-only for both the seat release and the shift cancellation.

## Step 9: Complete PRD — 2026-09-01T08:05:00.000Z

Subagent summary (verbatim):

## (a) Size

| | `PRD_FINALIZED.md` (source) | `PRD_COMPLETED.md` |
|---|---|---|
| lines | 483 | 483 (unchanged) |
| bytes | 111,319 | 131,274 → **+19,955** |
| characters | 110,835 | 130,683 → **+19,848** |
| headings | 28 | 28 (no new sections) |
| table rows | 146 | 146 (no table edits) |

114 diff lines = **57 changed lines**, all in-paragraph inserts/revisions.

## (b) Counts

**56 changes: 42 ambiguity-pins, 14 mismatch-revisions.**

## (c) Change log

- §2.1 — revise — mismatch — "may retract its own reviews" → "may retract a review": no ownership check exists on retraction — r_review.py:108-124
- §2.1 — revise — ambiguity — Volunteer ownership also matches a volunteer profile's own `id`, not only `volunteer_id`-bearing rows — rbac.py:82-86
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars; `api_request_timestamp` reads the logical clock, not wall time — envelope.py:13-21
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_VALIDATION`; empty string == omitted; tie-break is creation order, never `id` — payload.py:219-239, store.py:99-101
- §2.3 — insert — ambiguity — exact list of ownership-scoped listings for `Applicant`/`Volunteer`; construction-shift listing is not scoped — rbac.py:88-113, r_assignment.py:160-170
- §2.3 — insert — ambiguity — filter semantics: enum/bool/datetime filter failures → `ERR_VALIDATION`; identifier filter naming no row matches nothing; undeclared query params ignored — payload.py:241-280
- §2.4 — insert — ambiguity — a row is versioned at most once per request; a row created by the request stays at version 1; a repeat hop still refreshes `updated_at` — store.py:59-96
- §2.4 — insert — ambiguity — cost-entry 404 is `ERR_ENTRY_NOT_FOUND` — common.py:63-64
- §2.5 — insert — ambiguity — clock aliases `to_iso8601`/`current_utc_iso8601`/`now`, first present wins; parse failure → `ERR_VALIDATION`; response is a single `current_utc` field — r_clock.py:25-33
- §2.5 — revise — mismatch — every curriculum's `COMPLETED` enrollment expires, but only `HOMEBUYER_CORE` cascades to readiness — cascade.py:196-214
- §2.5 — insert — ambiguity — clock role checked only when a role header is offered; no header at all is accepted; `X-User-ID` never examined — r_clock.py:17-22
- §2.6 — insert — ambiguity — a supplied decimal with more than 2 places is `ERR_VALIDATION`, never silently rounded — payload.py:101-112
- §2.7 — insert — ambiguity — the version field must be an integer >= 1 — r_assignment.py:62, r_mortgage.py:73/234, r_program.py:86
- §2.8 item 7 — insert — mismatch — Volunteer's own profile added; seat reservation is the one endpoint where ownership follows payload validation (position 8) — r_assignment.py:67-83
- §2.8 item 8 — insert — ambiguity — a non-JSON-object or unparseable body is the same `ERR_VALIDATION` — payload.py:12-22
- §2.8 items 10/11 — revise — mismatch — **swapped**: 10 is `ERR_ALREADY_TERMINAL`, 11 is `ERR_TRANSITION_NOT_ALLOWED`; `REVERSED` added to terminals; enrollments treat only `FAILED`/`EXPIRED` as terminal and reviews treat neither as terminal — cascade.py:32-35, r_sweat.py:21, r_education.py:17
- §2.8 item 12 — revise — mismatch — exact enumeration of posture-guarded vs unguarded writes, plus the six writes where posture precedes 10/11 (and precedes 9 on seat reservation) — r_site.py:261-262, r_mortgage.py:376-380, r_assignment.py:86-93/201-202/230-231/260-261
- §3.1 — insert — ambiguity — `affiliate_name` uniqueness violation → `ERR_VALIDATION` — r_program.py:35-37
- §3.1 — insert — ambiguity — `delta_cents` >= 0, omitted = 0 (still versions the program), ignored by the two status actions — r_program.py:85,101,104
- §3.1 — insert — mismatch — `SUSPEND_PROGRAM` requires ACTIVE, `RESUME_PROGRAM` requires SUSPENDED, both `ERR_TRANSITION_NOT_ALLOWED` after the version comparison — r_program.py:89-99
- §3.2 — insert — mismatch — adding a member has no posture or state gate at all — r_household.py:263-293
- §3.2 — insert — ambiguity — submission's two conditions → `ERR_TRANSITION_NOT_ALLOWED` after origin/posture; `adult_occupant_count` re-derived on every read — r_household.py:137-142, derive.py:234-241
- §3.3 — insert — mismatch — `documented_reason` bound violations → `ERR_VALIDATION` (`ERR_VETO_REASON_REQUIRED` narrowed to an absent reason); household must be `COMMITTEE_REVIEW`; `retraction_reason` optional; any member may retract any review; neither review status terminal — r_review.py:44,48-50,64-66,113,115
- §3.3 — insert — ambiguity — filing/retracting writes willingness + composite onto the household from stored preliminary scores (null read as 0), bumps household version, leaves `score_basis`/`need_score`/`ability_to_pay_score`/`ami_pct` untouched — r_review.py:21-30
- §3.3 — revise — mismatch — quorum tested FIRST; a quorum failure writes nothing and leaves `score_basis` at `PRELIMINARY`; `decision_minutes` optional — r_household.py:231,238-242
- §3.3 — insert — ambiguity — waitlist-promotion response is a bare array with no pagination meta — r_program.py:135
- §3.3 — revise — ambiguity — return-to-screening `reason` is optional — r_household.py:212
- §3.4 — insert — ambiguity — rejection without `rejection_reason` → `ERR_VALIDATION` after state/posture/self-verification; resubmit requires both fields and re-tests `work_date`; household outside SELECTED/PARTNERSHIP_ACTIVE → `ERR_TRANSITION_NOT_ALLOWED` — r_sweat.py:138-139,155-163
- §3.4 — insert — ambiguity — credit: household state → `ERR_TRANSITION_NOT_ALLOWED`; member guard → `ERR_MEMBER_NOT_ACTIVE` before the waterfall — r_sweat.py:182-187
- §3.4 — insert — ambiguity — `reversal_reason` optional; three reversal preconditions all `ERR_TRANSITION_NOT_ALLOWED`; mirror field shape (capped_hours 0, null shift id, both user ids = reversing coordinator, version 1); response is the original, now `REVERSED` — r_sweat.py:237,243-275
- §3.4 — insert — ambiguity — shift-minted entry: both user ids = `crew_lead_user_id`, `work_date` = shift `start_at`, capped_hours 0, credit_weight/hours_credited null, version 1, not returned; minting silently skips an unresolvable member/household — r_shift.py:252-277
- §3.5 — insert — ambiguity — `module_code` mandatory 1-40; the first record moves `ENROLLED`→`IN_PROGRESS` either way; the passed-module set is internal and never echoed; a repeat pass still bumps version; the same code may be missed repeatedly — r_education.py:92-107
- §3.5 — insert — mismatch — completion/failure cascades fire only when readiness is exactly `EDUCATION_IN_PROGRESS` — r_education.py:114-129
- §3.5 — insert — ambiguity — governing core enrollment = latest by creation among live (`ENROLLED`/`IN_PROGRESS`/`COMPLETED`), else latest of all; never by `id` — derive.py:103-114
- §3.6 — insert — ambiguity — `parcel_number` uniqueness (per program) → `ERR_VALIDATION`; `acquisition_cost_cents` >= 0 — r_site.py:37,42-44
- §3.6 — insert — ambiguity — `ERR_DOCUMENTATION_INCOMPLETE` after the origin gate; TITLE repeat, UTILITIES precondition, FINAL_INSPECTION's two preconditions (open-shift first) all `ERR_TRANSITION_NOT_ALLOWED`; ENVIRONMENTAL adds none; readiness advance and safety posture are not posture-guarded — r_site.py:112-137
- §3.6 — insert — ambiguity — safety release falls back to `READY_TO_BUILD` when the captured pre-hold value is null — r_site.py:166
- §3.6 — insert — ambiguity — in-kind coherence test runs after posture; money fields default 0; `grant_award_code` never resolved; `void_reason` optional; re-void → `ERR_TRANSITION_NOT_ALLOWED`; the voided line's own record shows no version/`updated_at` change — r_site.py:196-200,258-266
- §3.7 — insert — ambiguity — `trade_certifications` entry validation → `ERR_VALIDATION`; stored normalized to exactly `trade` + `expires_on`, extras discarded — r_shift.py:316-326
- §3.7 — insert — ambiguity — `end_at <= start_at` or span > 10 h → `ERR_VALIDATION` before posture/safety/slot gates; `volunteer_slots` mandatory — r_shift.py:60,66-69
- §3.7 — insert — ambiguity — opening an already-started shift, and reopening with a `CHECKED_IN`/`COMPLETED` seat, both `ERR_TRANSITION_NOT_ALLOWED` — r_shift.py:146-153
- §3.7 — insert — ambiguity — locking at or after `start_at` → `ERR_TRANSITION_NOT_ALLOWED`, last of the four gates — r_shift.py:183-184
- §3.7 — insert — ambiguity — seat-field coherence → `ERR_VALIDATION` (ahead of ownership); shift must be `SCHEDULED`/`OPEN` → `ERR_TRANSITION_NOT_ALLOWED` — r_assignment.py:67-76,91-92
- §3.7 — insert — ambiguity — partner member must be `ACTIVE` → `ERR_MEMBER_NOT_ACTIVE`, right after the on-site test — r_assignment.py:112-113
- §3.7 — insert — ambiguity — confirm on a shift outside `SCHEDULED`/`OPEN` → `ERR_TRANSITION_NOT_ALLOWED`; missing or non-`ACTIVE` profile → `ERR_VOLUNTEER_SUSPENDED` — r_assignment.py:204-212
- §3.7 — insert — ambiguity — check-in on a shift not `LOCKED` or without the briefing → `ERR_TRANSITION_NOT_ALLOWED`; check-in bumps the parent shift's version too — r_assignment.py:233-246
- §3.8 — insert — ambiguity — `term_months` mandatory from exactly {240,300,360}; `escrow_monthly_cents` stored as supplied, null when omitted — r_mortgage.py:74-75,108
- §3.8 — revise — mismatch — *every* DRAFT is superseded; `superseded_application_id` records the last in creation order — r_mortgage.py:95-99
- §3.8 — insert — ambiguity — three household prerequisites all `ERR_HOUSEHOLD_NOT_SELECTED` in order; site readiness → `ERR_SITE_NOT_READY_TO_BUILD`; segregation ahead of all four; no site-already-assigned re-check on submit — r_mortgage.py:179-189
- §3.8 — insert — ambiguity — `ERR_NO_AFFORDABLE_STRUCTURE` leaves the two re-pinned snapshots persisted on a still-`DRAFT` file whose version does not move — r_mortgage.py:191-196
- §3.8 — insert — ambiguity — preview's eleven figures are the whole `data` object, no identifier echoed, available in any status, null snapshot read as 0 — r_mortgage.py:160-166, calc.py:310-340
- §3.8 — revise — mismatch — `closing_date` is request-only (both stored dates come from the logical clock); four conditions reordered education → site → sweat equity → readiness; readiness and non-positive silent second both `ERR_TRANSITION_NOT_ALLOWED` — r_mortgage.py:302,311-332
- §3.9 — insert — ambiguity — `effective_date` mandatory; non-`CLOSED` application → `ERR_TRANSITION_NOT_ALLOWED`, after posture and before the lien gates — r_mortgage.py:362,378-380
- §3.9 — insert — ambiguity — missing `counseling_session_reference` → `ERR_DOCUMENTATION_INCOMPLETE`, before the session count — r_mortgage.py:385-388
- §3.9 — revise — mismatch — transfer request on a non-`ACTIVE` lien is `ERR_ALREADY_TERMINAL`/`ERR_TRANSITION_NOT_ALLOWED`, **not** `ERR_LIEN_BALANCE_OUTSTANDING`; non-positive `sale_price_cents` → `ERR_VALIDATION`; notice price retained internally, never echoed — r_mortgage.py:380,399-403
- §3.9 — insert — ambiguity — `RECORD_TRANSFER` may reuse the notice price; the 25% band runs up to but not including the restriction mark (null restriction read as 240); recapture total and appreciation share internal; `lien_outstanding_cents`/`forgiven_amount_cents` not zeroed — r_mortgage.py:406-418, calc.py:380-396
- §3.9 — insert — ambiguity — SATISFY and RECORD_TRANSFER are the only lien actions that version the program — r_mortgage.py:416-424
- §3.9 — insert — ambiguity — grant `award_code` uniqueness → `ERR_VALIDATION`; `funder_name` 1-120 with `donor_name` alias; `award_amount_cents` >= 0 with `amount_cents` alias; `period_end > period_start` → `ERR_VALIDATION`; canonical spelling wins — r_grant.py:23-41, payload.py:25-39
- §3.9 — insert — ambiguity — `basis` literals `FULL_FMV_BASIS`/`CASH_BASIS`; report also carries `grant_award_id`, `award_code`, `households_served_target`; single object, no pagination meta — calc.py:420-467, r_grant.py:95-101

## (d) Coverage

All 22 implementation modules walked end to end: `util`, `errors`, `store`, `envelope`, `payload`, `rbac`, `derive`, `calc`, `cascade`, `common`, `app`, `r_program`, `r_clock`, `r_household`, `r_review`, `r_sweat`, `r_site`, `r_shift`, `r_assignment`, `r_education`, `r_mortgage`, `r_grant`.

Programmatic cross-checks: §5 error catalogue = 71 PRD rows vs 71 `ERROR_STATUS` entries, no missing/extra/status mismatch; §4 endpoint table = 71 impl routes vs 71 PRD rows, exact both directions; §2.3 filter field lists already matched every route's declared query parameters (only value semantics needed pinning). The four Step-8 patches (§3.2 final-basis write timing, §3.7 `safety_briefing_reference` request-only, §3.7 `cancellation_reason` request-only on both paths, §3.7 no-show hour release with permanent strike) verified present and left untouched.

---

## Pipeline complete — 2026-09-01T08:08:00.000Z

Final orchestrator verification:

- All nine artifacts present and non-truncated: `SCAFFOLD.yaml` (2898), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1449), `SCAFFOLD_CORNER_DESIGN.yaml` (2862), `workspace/INSTRUCTION.md` (53), `workspace/PRD.md` (483), `workspace/PRD_FINALIZED.md` (483), `workspace/PRD_COMPLETED.md` (483), `test_helpers/` (9 modules), `test_suite/` (14 test files + conftest, 119 tests), `workspace/implementation/` (22 modules + `start.sh` + `requirements.txt`).
- `results.{1..8}.json` all report **119 / 119**.
- No `implementation/` file was modified after the final passing sweep (latest impl mtime 04:37, sweep 07:25), so the recorded results still describe the code on disk.
- Storage audit re-run: no `sqlite3`, no `json.dump(`, no write-mode `open(`, no `/tmp/` path anywhere in `implementation/*.py` — in-memory dicts only, no startup seeding.
- Scratch fragments `_frag_rules_5_7.yaml` / `_frag_rules_8_9.yaml` and all `__pycache__` directories removed.
