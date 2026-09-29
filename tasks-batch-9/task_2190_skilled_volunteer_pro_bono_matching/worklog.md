# Worklog — task_2190_skilled_volunteer_pro_bono_matching

## Step 1: Create task directory — 2026-08-31T17:54:21.707Z

Created `tasks/task_2190_skilled_volunteer_pro_bono_matching/` and `tasks/task_2190_skilled_volunteer_pro_bono_matching/workspace/` (pre-allocated task directory name used verbatim; no index scan performed).

## Step 0: Resume-mode audit — 2026-08-31T18:10:00.000Z

Previous run crashed after Step 1. Directory audit found only `worklog.md` present — no SCAFFOLD.yaml, no SCAFFOLD_DIFFICULTY_DESIGN.yaml, no SCAFFOLD_CORNER_DESIGN.yaml, no workspace/INSTRUCTION.md, no workspace/PRD.md, no test_helpers/, no test_suite/, no workspace/implementation/, no PRD_FINALIZED.md, no PRD_COMPLETED.md. Pipeline resumed from Step 2 with the original task directory name retained.

## Step 3: Copy shared files — 2026-08-31T18:10:30.000Z

Copied `INSTRUCTION.md` (53 lines) to `tasks/task_2190_skilled_volunteer_pro_bono_matching/workspace/INSTRUCTION.md`. Run out of order relative to Step 2 (no dependency on the scaffold) while Step 2 executed in the background.

## Step 0: Resume-mode audit (second resume) — 2026-08-31T20:05:00.000Z

Prior run crashed during Step 2 (scaffold generation) — no scaffold artifact was written. Directory audit found exactly two files on disk: `worklog.md` and `workspace/INSTRUCTION.md`. `workspace/INSTRUCTION.md` re-verified byte-identical to project-root `INSTRUCTION.md` via `diff` → Step 3 confirmed valid, not regenerated. Missing / to regenerate: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, test_helpers/, test_suite/, workspace/implementation/, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md. Pipeline resumed at Step 2 with the original task directory name retained.

## Step 0: Resume-mode audit (third resume) — 2026-08-31T21:30:00.000Z

Prior run crashed again during Step 2 (scaffold generation) — still no scaffold artifact on disk. `find . -type f` returns exactly two files: `worklog.md` (1796 B) and `workspace/INSTRUCTION.md` (1424 B). `workspace/INSTRUCTION.md` re-verified byte-identical to project-root `INSTRUCTION.md` via `diff` → Step 1 and Step 3 confirmed valid, not redone. All remaining artifacts absent and to be generated: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, test_helpers/, test_suite/, workspace/implementation/, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md. Pipeline resumed at Step 2; task directory name retained verbatim.

## Step 0: Resume-mode audit (fourth resume) — 2026-08-31T22:40:00.000Z

Fourth resume. `find . -type f` still returns exactly two files: `worklog.md` and `workspace/INSTRUCTION.md`. `diff` against project-root `INSTRUCTION.md` → byte-identical, so Step 1 (directory) and Step 3 (shared-file copy) are confirmed valid and are NOT redone. Every other pipeline artifact is absent: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, test_helpers/, test_suite/, workspace/implementation/, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md. Step 2 has now crashed on three consecutive attempts without writing any scaffold file; this resume instructs the scaffold subagent to write each of the three YAML files to disk as a separate incremental Write/Edit sequence rather than buffering all three, so partial progress survives a crash. Pipeline resumes at Step 2; task directory name retained verbatim.

## Step 0: Resume-mode audit (fifth resume) — 2026-08-31T23:15:00.000Z

Fifth resume. `find . -type f` returns exactly two files: `worklog.md` and `workspace/INSTRUCTION.md`. `diff` against project-root `INSTRUCTION.md` → byte-identical, so Step 1 (directory) and Step 3 (shared-file copy) are confirmed valid and NOT redone. Every other artifact absent: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, test_helpers/, test_suite/, workspace/implementation/, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md. Step 2 has crashed on FOUR consecutive attempts without writing any scaffold file, which points at context exhaustion inside a single scaffold subagent (three large YAMLs in one context). Mitigation for this resume: Step 2 is split into three sequential subagents with independent fresh contexts — 2a writes SCAFFOLD.yaml (§1.0–§1.7), 2b reads SCAFFOLD.yaml and writes SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8), 2c reads SCAFFOLD.yaml and writes SCAFFOLD_CORNER_DESIGN.yaml (§1.9). Each writes its file to disk incrementally so partial progress survives a crash. Pipeline resumes at Step 2a; task directory name retained verbatim.

## Step 2a: Generate SCAFFOLD.yaml (§1.0–§1.7) — 2026-08-31T23:52:00.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_2190_skilled_volunteer_pro_bono_matching/SCAFFOLD.yaml` is complete — 2614 lines, valid YAML, §1.0 through §1.7 only.

**Complexity profile**
- Primary archetype: `multi_party_negotiation`; secondary: `quota_allocation`
- Complexity layers: selector_policy, dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers
- Structural dimensions: entity_topology `graph`, state_machine_shape `cyclic`, relationship_patterns one_to_many / many_to_many / self_referential / cross_aggregate, role_model `segregation_of_duties`, consistency_model `saga`
- Difficulty level: `beyond_expert`

**Section counts**
| Section | Count |
|---|---|
| §1.1 entities | 17 (11 with common_fields incl. `version`) |
| §1.2 state machines | 10 machines / 60 transitions (3 cyclic; `Engagement` carries two parallel dimensions `work_status` + `valuation_status`) |
| §1.2.1 concurrency rules | 3 (all create-with-supersede, OCC-only, 412) |
| §1.3 calculations | 10 (+3 conservation invariants) |
| §1.4 validations | 57 priority-ordered (+3 named `validation_priority_conflicts`) |
| §1.5 endpoints | 66 (40 writes / 26 reads, incl. `POST /_clock/set_current_utc` defaulting to `2026-08-01T00:00:00Z`) |
| §1.6 error codes | 56 |
| §1.7 roles | 5 (ProgramManager, ScopingSpecialist, Volunteer, PartnerContact, QualityReviewer) |

**Difficulty calibration (nine §0.5 rules, ≥2 differentiated instances each)**
- Dual-variant calc: `volunteer_hour_valuation` (MARKET_RATE per-line rounding + class factors vs INDEPENDENT_SECTOR flat $34.79 on summed hours) and `volunteer_reliability_score` (DECAY_WEIGHTED λ=0.85/N=8 vs LIFETIME_AVERAGE).
- Combinatorial formula, all three modes: (a) `match_score` 4-step selector with pinned ranking and empty-pool error, (b) `deliverable_quality_score` renormalised weights with per-item rounding, (c) `engagement_admin_overhead` tier keyed on base not total (documented trap: base 2380.00 → 0.12 → 2665.60).
- Non-linear machines: `ProjectRequest` (MATCHING branches to SCOPED/RESCOPING/ABANDONED on `failed_match_rounds`/`rescope_count`), `MatchOffer` (four terminals with explicitly divergent side effects), `EngagementAgreement` SENT↔COUNTERED, `QualityReview` OPEN→SCORED→REWORK_REQUESTED→OPEN.
- Transitive cascades: CASCADE-A depth 4 from `POST /match-offers/{id}/accept` (slot commit → FROZEN posture → mass offer withdrawal → hour release + forced RESCOPING); CASCADE-B depth 4 from `POST /quality-reviews/{id}/decide` FAIL (termination → RESTATED valuation → reliability recompute → volunteer PAUSED + offer withdrawal); plus a 5-hop partner-suspension cascade.
- Priority conflicts: state-beats-fiscal, safety-beats-referential, temporal-beats-constraint.
- Boundary precision: strict `<` reliability floor 0.4000, inclusive creep floors 0.1500/0.3000/0.5000, posture floors 0.8000/1.0000, PASS 78.00 / CONDITIONAL 60.00, overhead floor $45.00.
- Cross-entity state dependency: agreement EXECUTED gates start/time-logs/milestones/reviews; partner SUSPENDED and cycle posture gate matching.
- Resource temporal overlap with differing semantics: availability windows half-open with adjacency permitted vs milestone 72h closed buffer vs rolling 14-day check-in saturation cap of 2.
- Compensating invariants: `INV_CYCLE_SLOT_CONSERVATION`, `INV_VOLUNTEER_HOUR_CONSERVATION`, `INV_VALUATION_CONSERVATION` (three distinct conserved quantities).

**Linter status:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (66 endpoints, 17 entities). The linter requires all three design files, so the two downstream files were stubbed in `/tmp` (since deleted) purely to let the SCAFFOLD-level checks run; the initial run against the task directory only reported `file not found: SCAFFOLD_DIFFICULTY_DESIGN.yaml`, which is out of scope for this artifact. Additional self-checks passed: no forbidden concurrency vocabulary, zero undefined/unused error ids, and the RBAC matrix is exactly bidirectionally consistent with every endpoint's `roles:` (exclusive ops held by exactly one role).

*(Step 2 was split into 2a/2b/2c for crash resilience; this is the 2a summary, returned verbatim.)*

## Step 2c: Generate SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — 2026-09-01T02:35:00.000Z

Generated in two subagent passes (the first pass died to a transient API `server_error` at 4567 lines with all 7 sections present but endpoints/errors/rbac thin; a second fresh, narrowly-scoped subagent expanded those three sections). Final artifact verified valid YAML, single top-level key `scaffold_corner_design`, 6041 lines, 235 instances.

**Instance counts (all 7 sections)**
| section | count | status |
|---|---|---|
| entities | 25 | pass 1 |
| state_machines | 42 | pass 1 |
| calculations | 22 | pass 1 |
| validations | 36 | pass 1 |
| endpoints | 41 | expanded 7 → 41 in pass 2 |
| errors | 31 | expanded 6 → 31 in pass 2 |
| rbac | 38 | expanded 12 → 38 in pass 2 |

**Pass-2 summary (verbatim from subagent)**
- **endpoints (+34)**, in three bottom-up inserts before the `- section: errors` anchor. Coverage: missing-required-field, wrong-type, and unknown-enum payload rejections on `POST /partner-orgs`, `PATCH /partner-orgs/{id}/status`, `POST /program-cycles`, `POST /_clock/set_current_utc`, `POST /project-requests`, `POST /project-requests/{id}/scope-definitions`, `POST /scope-definitions/{id}/deliverables`, `POST /volunteers`, `POST /match-offers/{id}/decline`; unknown-path-id 404s for partner-org, program-cycle, scope-definition, volunteer, match-offer, milestone (plus the child-collection 404 contrast vs. empty 200); empty-collection reads for partner satisfaction surveys, cycle engagements, deliverables, skill-profiles, availability-windows, offers, engagements, agreements; pagination/filter edges (`offset` beyond end, `offset=-1` → 400 `ERR_INVALID_PAGINATION`, `limit` above ceiling, filter values that legally match nothing → 200/total_count 0).
- **errors (+25)**: each instance pins one error id's exact trigger, HTTP status, and the lower-priority error it outranks on the P1–P57 ladder — e.g. `ERR_MISSING_AUTH_HEADERS` (401) over schema validation, `ERR_ROLE_NOT_PERMITTED` (403) over not-found, the full not-found family (404) over state/business errors, `ERR_VALIDATION` over `ERR_ZERO_HOURS_NOT_ALLOWED` over `ERR_WINDOW_OUTSIDE_CYCLE` (all 422), `ERR_INVALID_REQUEST_STATE` (409) over `ERR_NO_ELIGIBLE_VOLUNTEER`, `ERR_VOLUNTEER_NOT_ACTIVE` over `ERR_DUPLICATE_SKILL_PROFILE`, `ERR_INVALID_SCOPE_STATE` over `ERR_DELIVERABLE_WEIGHT_TOTAL_INVALID`, `ERR_INVALID_AGREEMENT_STATE` over `ERR_IP_TERMS_MISMATCH`, plus `ERR_CLOCK_REGRESSION`.
- **rbac (+26)**: negative cells for every role-exclusive write in the segregation-of-duties model — Volunteer/PartnerContact/ScopingSpecialist/QualityReviewer each attempting operations reserved to another role and receiving 403 `ERR_ROLE_NOT_PERMITTED` contradicting that endpoint's declared `roles=[...]`; plus own-resource cells returning `ERR_NOT_RESOURCE_OWNER` (foreign volunteer publishing a window or accepting another's offer, foreign PartnerContact approving another org's scope) and role-scoped read denials.

**Notable domain decisions**
- `capacity_slot_total: 0` asserts `ERR_VALIDATION`, not `ERR_ZERO_HOURS_NOT_ALLOWED` — the scaffold scopes the latter to the five hour-valued inputs only. Same reasoning applied to `weekly_hours_cap: -5`.
- `ERR_VOLUNTEER_NOT_ACTIVE` is triggered by a PAUSED volunteer re-claiming an existing skill code, not a PENDING_VETTING claim: the canonical chain posts skill-profiles *before* vetting, so PENDING_VETTING claims must succeed.
- `POST /volunteers/{id}/vet` with an unheld skill code is 200 (set intersection, not lookup) — status flips to ACTIVE, the unnamed claim stays `verified == false`.

No other file was read or written: `SCAFFOLD.yaml` was consulted read-only in four targeted slices, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` was never touched, and no sibling task directory was accessed.

## Step 2b: Generate SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — 2026-09-01T04:20:00.000Z

Step 2b required six subagent passes. The first three attempts (one original + two retries, including one context-preserving resume) died to stalls or transient API `server_error`s; the third left five complete rule blocks on disk (2317 lines). The remaining four rules were then generated by four PARALLEL single-rule subagents, each writing to its own scratch file under /tmp to avoid write contention, and the orchestrator concatenated them. A final subagent fixed the lint violations. Final artifact: 5846 lines, valid YAML, single top-level key `scaffold_difficulty_design`, 9 rules / 35 instances, lint clean.

**Rule blocks and instance counts (file order)**
| rule_id | instances | provenance |
|---|---|---|
| dual_variant_calc | 2 | pass 1-3 |
| combinatorial_formula | 3 | pass 1-3 |
| non_linear_state_machine | 4 | pass 1-3 |
| transitive_cascade | 3 | pass 1-3 |
| priority_pair_validation_conflict | 3 | pass 1-3 |
| boundary_precision | 5 | parallel agent (scratch) |
| cross_entity_state_dependency | 5 | parallel agent (scratch) + 1 appended instance |
| resource_temporal_overlap | 5 | parallel agent (scratch) |
| compensating_invariant | 5 | parallel agent (scratch) |

**boundary_precision (verbatim from subagent)**
1. `reliability_floor_strict_at_0_4000` — strict `<` floor. Key finding: 0.4000 is **unreachable** with 1–3 terminal engagements because MISSED_CHECKIN_LIMIT 2 confines single-engagement points to {1.00, 0.90, 0.70, 0.60, 0.50, 0.25, 0.15, 0.05, 0.00}. Minimum construction is 4 terminal engagements with points 0.25/0.60/0.50/0.25 → num 1.27478125 / sum(w) 3.186625 = 0.4000 (stays ACTIVE, match 201); one extra missed check-in on the oldest → 0.3808 → PAUSED + `ERR_NO_ELIGIBLE_VOLUNTEER`; just-above 0.4227.
2. `creep_band_floors_inclusive_ladder` — 0.1500/0.3000/0.5000 walked as one rising ladder on baseline 40.00: 45.99→0.1498 NONE, 46.00→0.1500 WATCH, 51.99→0.2998, 52.00→0.3000 ESCALATED, 59.99→0.4998, 60.00→0.5000 BREACH (terminates inside a 200 hold). Finding: after BREACH the next time-log answers `ERR_INVALID_WORK_STATE` (P23), so the only reachable `ERR_SCOPE_BREACH_THRESHOLD` (P56) path is a PENDING scope change (projection 0.4000 → MANAGER_REVIEW); creep can never sit at BREACH via pending alone since a 0.5000 projection is VOIDED as RESCOPE_REQUIRED.
3. `cycle_posture_floors_on_integer_slot_lattice` — 7/10=0.7000 OPEN, 8/10=0.8000 RESTRICTED (ROUTINE→409 `ERR_CYCLE_RESTRICTED_URGENCY`, ELEVATED→201), 10/10=1.0000 FROZEN (CRITICAL→409 `ERR_CYCLE_CAPACITY_FROZEN`, P51 before P52), handoff→0.9000. Finding: FROZEN reached via a reservation self-reverses (offer WITHDRAWN → 0.9000 RESTRICTED), so only committed slots hold FROZEN stably.
4. `quality_gate_thresholds_78_and_60_with_pinned_rounding` — 78.00 (90/10 @ 4,3), 77.99 (89.95/10.05), 78.01 (90.05/9.95), 60.00 (50/50 @ 3,3), 59.99 (99.95/0.05 @ 3,2 → FAIL + CASCADE-B), 60.01 (@ 3,4), plus a rounding-order discriminator 16.62/60.17/23.21 @ 2,4,5 → pinned 6.65+48.14+23.21 = **78.00 PASS** vs summing unrounded 77.994 → **77.99 CONDITIONAL**.
5. `admin_overhead_minimum_charge_clamp_at_45` — base lattice is 0.75-grained at rate 150.00, so the clamp's dead zone is pinned: 374.25 → 44.91 clamped to 45.00 (total 419.25), 375.00 → 45.00 exactly (420.00), 375.75 → 45.09 (420.84). Plus TRAVEL-only base 0.00 → overhead 45.00/total 45.00 (and INDEPENDENT_SECTOR 104.37 → clamped, total 149.37), and the tier floor bracketed at 2499.75 (0.12 → 299.97) vs 2500.50 (0.09 → 225.05), with 2380.50 → 285.66/2666.16 as the tier-from-base proof.
One correction made while writing: `POST /quality-reviews/{id}/decide` takes `request_rework`, not an `outcome` — the outcome comes from the score step, so instance 1's CONDITIONAL history engagement now gets it via a weight-100.00 deliverable scored 3 (weighted_score 60.00).

**cross_entity_state_dependency** — instances: `agreement_execution_gates_engagement_start`, `unexecuted_agreement_blocks_time_log_via_work_state`, `unexecuted_agreement_blocks_milestone_checkin_two_hops`, `pinned_scope_authorship_gates_quality_review_open`, plus `frozen_cycle_posture_and_suspended_partner_block_new_commitments`. The fifth pins two remote gates: `POST /project-requests/{id}/match` refused with `ERR_CYCLE_CAPACITY_FROZEN` (P51, 409) while the ProjectRequest's own status is `SCOPED` (FROZEN reached with `capacity_slot_total: 1` plus one OFFERED hold → `utilization_ratio` exactly 1.0000; withdrawing the sibling offer returns posture to OPEN and the identical call then returns 201 — the gate-opening proof); and `POST /project-requests` refused with `ERR_PARTNER_SUSPENDED` (P31, 403). Key design finding documented inside the instance: the suspension gate cannot be probed on the match endpoint, because the PartnerOrg `ACTIVE -> SUSPENDED` cascade abandons every request of that partner in DRAFT/SCOPING/SCOPED/MATCHING/RESCOPING and WITHDRAWs their OFFERED offers, so a post-suspension match would trip P20 `ERR_INVALID_REQUEST_STATE` first and stop isolating the remote cause; the same cascade drives DRAFT ScopeDefinitions to WITHDRAWN, ruling out `POST /scope-definitions/{id}/approve` as an alternative probe.

**resource_temporal_overlap (verbatim from subagent)** — instances `availability_window_half_open_adjacency_versus_one_second_overlap`, `milestone_checkin_buffer_closed_72h_boundary`, `rolling_fourteen_day_checkin_saturation_slides_by_candidate_due_at`, `half_open_window_versus_closed_buffer_same_instant_contrast`, `availability_window_cycle_containment_boundary_and_degenerate_interval`.
- **Half-open `[start, end)` overlap** (P43, `ERR_AVAILABILITY_WINDOW_OVERLAP`, 409): both adjacency directions accepted — new window at `[2026-03-01, 2026-03-15)` touching `win.ends_at`, and `[2026-01-02, 2026-01-05)` touching `win.starts_at`; then two one-second true intersections rejected — `[2026-02-28T23:59:59Z, 2026-03-01T00:00:00Z)` and `[2026-01-05T00:00:00Z, 2026-01-05T00:00:01Z)`.
- **Closed 72h `CHECKIN_BUFFER_HOURS`** (P44, `ERR_MILESTONE_SPACING_VIOLATION`, 409): against an anchor at `2026-01-20T00:00:00Z`, `71:59:59` on both sides rejected (proving `abs()` symmetry), exactly `72:00:00` (`2026-01-23T00:00:00Z`) accepted, and `72:00:01` accepted against an *isolated* anchor at `2026-02-15T00:00:00Z` (deliberately >7d from all earlier milestones so P45 cannot mask the boundary).
- **Rolling closed 14-day span, cap 2** (P45, `ERR_VOLUNTEER_CHECKIN_SATURATED`, 409): with siblings at `01-20` and `01-23`, candidate `01-26` refused; the clock is then advanced to `2026-01-19T00:00:00Z` and `01-27T00:00:00Z` is *still* refused (span lower edge `2026-01-20T00:00:00Z` lands exactly on the oldest sibling — closed edge counts it, and the clock is not the anchor); `01-27T00:00:01Z` is accepted because the span slides to `2026-01-20T00:00:01Z`, dropping the count to 1.
- Instance 4 asserts the divergence on one instant: `2026-03-01T00:00:00Z` is *outside* the window for `Milestone.due_at` (422 `ERR_MILESTONE_DUE_OUTSIDE_ENGAGEMENT`) yet legal as a new window's `starts_at` (201). Instance 5 uses exact-boundary acceptances then one-second breaches on each side plus a degenerate zero-length interval, all `ERR_WINDOW_OUTSIDE_CYCLE`; the two breaches also overlap existing windows, pinning P39 before P43.

**compensating_invariant (verbatim from subagent)**
1. `cycle_slot_released_exactly_on_termination` — INV_CYCLE_SLOT_CONSERVATION. accept commits, terminate releases; 1+0+9==10 → 0+0+10==10, utilization_ratio 0.1000 → 0.0000, posture OPEN; asserts committed never exceeds capacity_slot_total 10. Carries the full canonical empty-DB → IN_PROGRESS chain (19 calls) reused by the other four.
2. `window_hours_release_matches_grown_commitment` — INV_VOLUNTEER_HOUR_CONSERVATION. Commitment grows before release: AUTO_APPROVABLE ScopeChangeRequest (projected_creep_pct = round((0.00+0.00+12.00-40.00)/40.00,4) = -0.7000) pushes committed_hours 40.00 → 52.00, so terminate must release 52.00 → hours_committed exactly 0.00 / hours_remaining 300.00 (no cent drift).
3. `valuation_restatement_conserves_lifetime_total` — INV_VALUATION_CONSERVATION. Approved logs DELIVERY 34.50 + ADMIN 3.50 + TRAVEL 2.00 = 40.00h; INDEPENDENT_SECTOR base round(40.00x34.79,2)=1391.60, tier 0.12 → overhead max(45.00, 166.99)=166.99, total 1558.59. FAIL decision (weighted_score round(1.000000x2x20,2)=40.00 < 60.00) supersedes the PROVISIONAL record and posts a RESTATED one of the same 1558.59; lifetime_valued_usd stays 1558.59, excluding 3117.18 and 0.00; exactly 2 records, exactly 1 non-superseded.
4. `repeated_termination_does_not_release_twice` — idempotence (slot + hour). Replayed terminate refused with 409 / `ERR_INVALID_WORK_STATE` (P23); counters unchanged (0/0/10, 0.00/300.00, terminal_engagement_count 1, reliability 0.2500), excluding the -1/11 and -40.00/340.00 double-release outcomes.
5. `shared_window_releases_only_terminated_engagement_share` — multi-consumer. Two engagements of one volunteer on one window: 40.00+40.00 = 80.00 committed / 220.00 remaining; terminating A leaves hours_committed 40.00 / remaining 260.00 and slots 1/0/9 with utilization 0.1000, while B stays NOT_STARTED at 40.00 — and the ADMIN-termination reliability drop to 0.2500 pausing the volunteer must not sweep B's hold.
Invariant coverage: SLOT → instances 1, 4, 5; HOUR → 2, 4, 5; VALUATION → 3.

**Lint-fix pass (40 violations → clean).** All 40 were confined to the two blocks whose agents were deliberately barred from reading the §1.5 endpoints spec.
- Expanded placeholder chains — 4 (class (a) malformed call string): each prose placeholder at `setup_api_calls[0]` in `compensating_invariant` replaced with the literal 19-call empty-DB → IN_PROGRESS chain from instance 1, captures tuned per the placeholder's own text; the 8 request-B calls following the placeholder in instance 5 preserved untouched.
- Renamed keys — 2 (near-miss misnames, values preserved so no asserted number moved): `hours_reported` → `reported_cumulative_hours` on `POST /milestones/${ms2b}/hold`; `rationale` → `justification` on `POST /engagements/${eng}/scope-change-requests`. Each rename cleared both an undeclared-key and a missing-required-field violation.
- Added required fields — 0 new literal values invented (both class-(2) violations were the flip side of the two renames).
- Deleted keys — 34 across 27 calls: `note` off 8 terminate / 3 time-log / 2 hold calls; `sequence_no`, `title`, `expected_hours` off 10 `POST /engagements/{id}/milestones` calls (endpoint declares only `due_at`); `stage: "PROVISIONAL"` off 8 `POST /engagements/{id}/valuations` calls.

**Final linter verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` No violations reported against SCAFFOLD_CORNER_DESIGN.yaml; SCAFFOLD.yaml untouched.

## Step 4: Generate PRD — 2026-09-01T04:45:00.000Z

PRD.md is complete at `workspace/PRD.md`.

## Final line count
**483 lines** (ends at the last row of the §5 error table; no audit footer in the file).

## Section outline
- `# Pro Bono Matching API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (byte-verbatim block) · 2.3 Pagination · 2.4 Resource Identity, Audit Stamps and Version Counters · 2.5 The Logical Clock and Interval Geometry · 2.6 Numeric Precision and Rounding · 2.7 Stale-Version Guards on Superseding Writes · 2.8 Cycle Slots as a Conserved Capacity Ledger · 2.9 Volunteer Hour Custody · 2.10 Valuation Conservation and Restatement · 2.11 Nested Path Resolution · 2.12 Rejection Precedence
- `## 3. Business Logic & Workflows` — 3.1 Partner Enrolment and Program Capacity Posture · 3.2 The Volunteer Roster: Vetting, Skills and Availability · 3.3 From Project Request to an Approved Scope · 3.4 Matching: The Selector, the Offer and the Reservation · 3.5 Offer Outcomes: Acceptance, Refusal and the Re-Scoping Loop · 3.6 Negotiating IP and Confidentiality Terms · 3.7 Delivery: Check-ins, Hours and Scope Creep Control · 3.8 Quality Review, Rework and Handoff · 3.9 Termination, Hour Valuation and Partner Feedback
- `## 4. API Endpoint Definitions` (4-column table, 66 rows)
- `## 5. Error Codes` (2-column table, 56 rows)

## Coverage self-audit (machine-verified against SCAFFOLD.yaml)
- **Entities (17):** all 151 `entities[].fields[].name` identifiers appear verbatim in backticks. All 17 entity names appear; §2.4 states which 12 carry `updated_at`/`version` and which 5 carry only `id`/`created_at`.
- **State machines (10 / 60 transitions):** every state name appears; all 60 transitions are represented, 52 as explicit `FROM → TO` arrows and 8 as prose within a single sentence naming both endpoints of the move (e.g. the four manual `→ ABANDONED` branches, each with its own distinct side-effect set preserved). Sibling-branch asymmetry kept (abandon from `DRAFT`/`MATCHING` releases offers; from `SCOPING`/`SCOPED` withdraws revisions; from `RESCOPING` only stamps `closed_at`).
- **Concurrency (3):** §2.7 covers all three OCC guards (`expected_project_request_version`, `expected_engagement_version` on both valuations and agreements) purely in stale-version terms; no "simultaneous"/"race"/"first-writer" language anywhere in the file.
- **Calculations (10):** all ten fully specified with both variants where present (`volunteer_hour_valuation`, `volunteer_reliability_score`); every numeric constant in every calculation block appears literally in the PRD (verified per-calculation), including per-line vs single-shot rounding order, the overhead-tier-from-base ordering, and normalised-weight rounding depths.
- **Invariants (3):** §2.8/2.9/2.10 state each conserved formula plus its forward/compensating behavioural requirement, including the 40.00 → 52.00 release example and the non-superseded `INDEPENDENT_SECTOR` sum.
- **Validations (57):** §2.12 is a 1-to-57 ordered list; every priority number maps to the scaffold's priority, every `error_id` is named on its own line with HTTP status, and every endpoint in every `applies_to` scope is echoed on its line (0 gaps). The 3 `validation_priority_conflicts` follow as named dual-failure cases with the winning error.
- **Endpoints (66):** §4 table has exactly 4 columns; all 66 method+path pairs present and each row's role set matches the scaffold's `roles` exactly (0 mismatches). No trigger conditions or bodies in the table.
- **Errors (56):** §5 table has exactly 2 columns; all 56 IDs with the scaffold's exact HTTP statuses. Every error ID is also referenced at least once in §2 or §3 prose at its trigger site.
- **RBAC (5 roles):** §2.1 names all five roles, both identity translations for the entity-backed pair, the four auth error IDs, and the SoD barrier (both `authored_by_user_id` and `reviewer_user_id` clauses); the per-endpoint authorization matrix is the §4 role column.

## Hard Contracts
- **Contract 1 (Field-Name Coverage): PASS** — 151/151 entity field names and 76/76 endpoint `input` identifiers present verbatim in backticks (two verification passes; the single initial gap, `engagement_id`, was repaired by adding the parent-reference rule to §2.11).
- **Contract 2 (Rule Coverage): PASS** — see audit above; every transition, calculation, invariant, validation priority, cascade (CASCADE-A, CASCADE-B) and cross-entity side effect is reachable from the prose.
- **Contract 3 (§3 Path Purity): PASS** — 0 backticked tokens in §3 start with `/`, are a bare HTTP method, or combine method+path; 0 unbackticked method+path or bare-path occurrences in §3.

One scaffold inconsistency worth flagging: `ERR_RESCOPE_LIMIT_REACHED`'s condition text says `MAX_RESCOPES (2)` while the `ProjectRequest` state machine and validation priority 50 both say `MAX_RESCOPES (3)`. The PRD follows the state machine / validation value of **3** consistently.

## Step 6: Generate implementation — 2026-09-01T06:20:00.000Z

The implementation is complete and verified.

## Files written (all under `workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `requirements.txt` | 1 | `flask>=2.0.0` |
| `start.sh` | 8 | guarded pip install (skipped when Flask already importable, so per-test reboots are instant), then `exec python3 app.py` |
| `app.py` | 73 | app factory, 6 blueprints, `before_request` auth (ladder priorities 1-2), ApiError/404/405/500 handlers, `PORT` default 10000 |
| `config.py` | 210 | every enumeration + declared constant (`MAX_RESCOPES = 3` per the PRD adjudication, `MAX_COUNTER_ROUNDS = 3`, `CHECKIN_SATURATION_LIMIT = 2`, `REWORK_DEADLINE_HOURS = 168`, posture/creep/tier bands, weight ladders) |
| `errors.py` | 80 | the literal 56-code → HTTP status map, `ApiError`, `fail()` |
| `store.py` | 142 | 17 in-memory dict tables, logical clock, id/seq/version helpers |
| `response.py` | 123 | §2.2 envelope, `req_` + 20-char id, 3-fraction-digit ISO timestamps, offset pagination |
| `calc.py` | 548 | the 10 calculations + all derived ledgers, `Decimal`/`ROUND_HALF_UP` throughout |
| `serialize.py` | 378 | one serializer per entity; `updated_at`/`version` omitted for the five light kinds |
| `guards.py` | 635 | the ladder as `g01`…`g57`, role registry, typed field validators |
| `domain.py` | 350 | every cascade (offer release/branching, CASCADE-A freeze sweep, CASCADE-B fail chain, termination release chain, partner suspension, satisfaction rebuild, cycle checkpoint) |
| `routes/__init__.py` | 1 | package docstring |
| `routes/partners.py` | 103 | partner-org group |
| `routes/cycles.py` | 81 | program-cycle group + `POST /_clock/set_current_utc` |
| `routes/requests.py` | 371 | requests, scope revisions, deliverables, matching |
| `routes/volunteers.py` | 201 | volunteers, vetting, skill claims, availability windows |
| `routes/offers.py` | 135 | offer read/accept/decline/withdraw |
| `routes/engagements.py` | 828 | agreements, milestones, time logs, scope changes, submit, reviews, handoff, terminate, valuations, surveys |
| **total** | **4268** | |

Endpoint parity was checked mechanically: the 66 `(method, path)` rows of PRD §4 and Flask's `url_map` match exactly — zero missing, zero extra.

## The 57-priority validation ladder
`guards.py` defines one function per global priority, named for its number (`g01_auth_headers` … `g57` via `ERR_NO_ELIGIBLE_VOLUNTEER`), so a handler's guard calls read as an ascending sequence and the ordering is auditable by eye. Priorities 1-2 (auth headers, role permission) run in `app.before_request` against a `ROLE_REGISTRY` populated by the `route()` decorator, keyed `"<blueprint>.<endpoint>"`; the hook returns early when `request.url_rule is None` so the router still answers 404/405 first. Priorities 3-13 are the path-segment existence guards; 14 resolves body foreign keys *before* schema judgement (so an unresolvable `partner_org_id` yields 404, not 422); 15-16 ownership and segregation of duties; 17-19 schema/pagination/zero-quantity; 20-28 the per-machine from-set guards; 29-30 the OCC guards; 31-57 the business guards. Every guard raises `ApiError` immediately, so the first failure short-circuits with no side effects. Ordering was spot-checked against the PRD in the collision cases (e.g. a stale `expected_engagement_version` on a valuation still loses to priority 24 `ERR_INVALID_VALUATION_STATE`, which is what the ladder demands).

## The three conservation invariants
None of them is ever incremented — all three are derived at read time in `calc.py`, so no compensating write can drift:
1. **Cycle slots** — `cycle_metrics()` counts `slots_committed` as the cycle's engagements in the four live `work_status` values and `slots_reserved` as the `OFFERED` offers whose request belongs to the cycle, then derives `slots_available`, `utilization_ratio` (4 dp) and `posture` from those counts.
2. **Availability-window hours** — `window_metrics()` recomputes `hours_committed` as Σ`reserved_hours` of `OFFERED` offers on the window plus Σ`committed_hours` of live engagements pinned to it (the *grown* figure, including approved scope-change hours), and `hours_remaining` as `hours_offered` less that sum.
3. **Volunteer lifetime valued USD** — `lifetime_valued_usd()` sums `total_amount_usd` over the volunteer's non-superseded `INDEPENDENT_SECTOR` valuation records only, so a restatement (supersede + compensating record) can never double-count.

Same discipline for `approved_hours`, `scope_creep_pct`, `missed_checkin_count`, both reliability variants, `active_scope_revision_no`, `open_engagement_count` and the deliverable count/weight totals.

## The logical clock
`store.py` holds `_clock = {"now": parse_iso("2026-08-01T00:00:00Z")}`; `S.now()` is the only time source in the codebase — no `datetime.utcnow()` anywhere, including `api_request_timestamp`, which is stamped from the same clock. `POST /_clock/set_current_utc` accepts an instant ≥ the current reading (equal is a no-op) and rejects earlier ones with `ERR_CLOCK_REGRESSION` (422). Advancing performs no sweep; expiry and neglect only materialise in `domain.recalculate_cycle()`.

## Boot check
`pkill`-ed everything, then `cd <implementation dir> && PORT=19733 bash start.sh` from a fresh process:
- `GET /project-requests?limit=10` → `200`, `{"meta": {"api_request_id": "req_WA2Y9N198QTNW3Y42EBK", "api_request_timestamp": "2026-08-01T00:00:00.000Z", "limit": 10, "offset": 0, "total_count": 0, "has_more": false}, "response_type": "array", "data": []}` — envelope matches §2.2, clock reads exactly the startup instant, and **state is empty: nothing is seeded**.
- `POST /program-cycles` → `201` with `response_type: "object"` and a cycle reading `slots_available: 3`, `utilization_ratio: 0.0`, `posture: "OPEN"`, `recalc_epoch: 0`, `version: 1`.
- Server then killed; both test ports confirmed down, no stray processes, no files written to disk (only `__pycache__`).

## Correctness verification performed
Four end-to-end scripts (~120 assertions) over fresh processes exercised: the full happy path; decline/retry-exclusion/no-eligible-volunteer; the checkpoint expiry sweep and epoch advance; the counter-limit → agreement void → termination chain; two missed check-ins → `ADMIN` termination → reliability 0.05 → `PAUSED`/`RELIABILITY_FLOOR`; the FAIL-review cascade (`RESTATED` + compensating `INDEPENDENT_SECTOR` record + `lifetime_valued_usd` rebuild + slot/hour release); `RESCOPE_REQUIRED` → `SCOPE_BREACH` + `RESCOPING`; partner suspension; `RESTRICTED`-tier handoff; rework round 2 with the same-reviewer SoD bar; MANAGER_REVIEW approval; the survey composite/index; and a 30-endpoint GET sweep (the only non-200s were three singleton GETs the PRD does not declare). Hand-checked figures all matched: match score 0.906, quality scores 20.00/70.00/80.00/92.00/100.00 with correct outcome bands, MARKET_RATE 1300.00 + 156.00 = 1456.00 and 2560.00 + 230.40 = 2790.40, INDEPENDENT_SECTOR 347.90 + 45.00 floor = 392.90 and 417.48 + 50.10 = 467.58, satisfaction 82.00/95.00, and the decay-weighted vs lifetime reliability pair (0.5405/0.5750 at two terminal engagements, 0.3304/0.3833 at three).

One gap found and fixed while testing: `resulting_scope_revision_no` on a VOIDED escalated scope-change request was never back-stamped. Added `domain.stamp_forced_rescope_result()`, called when a new revision is drafted on the request, and verified it now records the revision the forced re-scope produced.

## Step 5: Generate Unit Tests — 2026-09-01T01:05:00.000Z

Step 5 was executed as a **fan-out**, not a single agent: the first test-generator agent died with an API error after completing queue A (138 Design tags), so the orchestrator ran a coverage audit, confirmed queue A complete (all 35 Difficulty instances covered), and then dispatched **one agent per `SCAFFOLD_CORNER_DESIGN.yaml` section** for queue B. Each agent was given `test_helpers/` READ-ONLY, `workspace/implementation/` forbidden, sibling test files forbidden, `test_10_entity_shapes_and_lookups.py` as structural template, the single-verbatim-`Design:`-line contract, the two-condition PRD-first filter (skip, never weaken/xfail), and the MAX_RESCOPES=3 PRD-wins adjudication.

### Final audit (orchestrator-run, mechanical)

```
available design instances : 270  (Difficulty 35 + Corner 235)
covered distinct instances : 265
total Design tags in suite : 344
tags pointing at non-existent instances : 0
uncovered instances : 5   (all deliberate, justified skips)
pytest --collect-only     : 344 tests collected in 0.98s
```

Per-file test counts:

```
test_01_dual_variant_valuation_and_reliability.py   8
test_02_combinatorial_formulas.py                   7
test_03_state_machine_branching.py                 13
test_04_transitive_cascades.py                     10
test_05_rejection_precedence_pairs.py               9
test_06_boundary_precision.py                      31
test_07_cross_entity_state_gates.py                11
test_08_temporal_geometry.py                       12
test_09_entity_shapes / conserved_ledgers.py       13
test_10_entity_shapes_and_lookups.py               24
test_11_state_machine_corners.py                   41
test_12_endpoint_corners.py                        40
test_13_rbac_matrix.py                             38
test_14_validation_ladder.py                       35
test_15_error_catalog.py                           30
test_16_calculation_corners.py                     22
                                            total 344
```

### The 5 skipped instances (each fails the two-condition filter)

- `Corner/entities/create_volunteer_client_supplied_system_fields_are_input_ignored` — fails (b). PRD never states how unrecognised or system-owned request-body keys are treated; §2.12 item 17 defines conformance only as required-fields/enum/range/ISO-8601. A strict-schema implementer returns 422, a lax one 201. Not uniquely determined.
- `Corner/endpoints/endpoint_create_partner_org_wrong_type_budget_rejected` — fails (b). §2.12 item 17 names no error for a *type* mismatch, and `annual_budget_usd: "3000000"` is a coercible numeric string, so 201 is a legitimate PRD-faithful answer. (The two non-coercible wrong-type instances, `"high"` for `complexity_factor` and `"first"` for `sequence_no`, WERE kept.)
- `Corner/errors/error_volunteer_not_active_beats_duplicate_skill_profile` — fails (a). §2.12 item 33 scopes the not-active check to exactly four endpoints (accept, start, time-logs, submit) and §3.2 repeats the same four; `POST /volunteers/{id}/skill-profiles` is in neither list, so PRD states no such rule.
- `Corner/state_machines/sm_partner_suspended_terminal_cannot_return_to_active` — fails (b). PRD declares `SUSPENDED` terminal but names no `error_id` for a refused partner-status transition, and `ERR_VALIDATION` does not uniquely follow because `ACTIVE` is a declared enum member.
- `Corner/validations/val_same_reviewer_cannot_open_second_round_segregation_of_duties` — fails (b). §2.1 bars an operator "who owned a prior round"; §3.8 bars an operator "other than the one who owned a prior round" — exactly opposite for this scenario. Two faithful readers land on opposite outcomes.

### Cross-cutting PRD-over-scaffold adjudications applied by multiple agents

- `quality_gate` on a fresh engagement is `PENDING`, not `null` (PRD §3.5 creation defaults). Applied in test_11, test_13, test_14.
- `outcome` on a fresh quality-review round is `PENDING`, not `null` (PRD §3.8). Applied in test_11, test_13, test_14.
- The deliverable score payload key is `review_score` (PRD §3.8), not the scaffold's `score`. Applied in test_11, test_14, test_16.
- `started_at`, `executed_at`, `review_round_count`, `last_recalculated_at` are NOT PRD-declared fields — every assertion on them was dropped rather than the test being skipped.
- Scaffold payloads carrying values outside PRD's declared enums (`sector: HUMAN_SERVICES`, `ip_disposition: LICENSE_TO_PARTNER`, `RETAIN_BY_VOLUNTEER`, `PRIVILEGED`) were replaced with declared values so no test accidentally leans on priority-17 firing before the intended rule.
- `ERR_CLOCK_REGRESSION`: PRD §2.5/§2.12 item 42 say an *equal* instant is accepted ("at or after"), contradicting the scaffold's 422 expectation. Tests assert equal→200, strictly-earlier→422.
- `MAX_RESCOPES` = **3** everywhere (PRD §2.12 item 50), per the orchestrator's standing PRD-wins adjudication of the scaffold's inconsistent `ERR_RESCOPE_LIMIT_REACHED` condition text.
- Timestamps the PRD does not tie to the logical clock (`decided_at`, `superseded_at`, `handoff_at`, `expires_at`) are asserted non-null or via a local `_instant()`/`_same_instant()` ISO parse, never by raw string equality, because §2.4 mandates three fractional digits on `created_at`/`updated_at` only.

### Unreachable-state adjudications (trigger changed, instance claim preserved)

- `calc_cycle_posture_frozen_at_exactly_full_utilization` and `val_frozen_cycle_blocks_second_match`: utilization is `(committed + reserved)/total`, so a 1-slot cycle is already `FROZEN` from the open offer alone and the accept is refused by priority 51. Both tests trigger on `match` and assert the instance's actual claim (utilization exactly 1.0000, inclusive FROZEN floor, slot conservation).
- `conflict_confidentiality_attestation_beats_pinned_revision_check`: the doubly-violating state is unreachable through declared endpoints, so the test drives the reachable half and pins the winner plus the still-`APPROVED` pinned revision.
- `error_rescope_limit_reached_on_fourth_rescope_attempt`: the scaffold's `ADMIN` withdrawals explicitly do NOT raise `failed_match_rounds` (§3.5), so the drive was rebuilt on six distinct vetted volunteers and six `SCHEDULE_CONFLICT` declines respecting the retry exclusion.
- `sm_quality_review_round_two_reopens_cycle_after_rework`: round two is opened by the SAME reviewer (§3.8), not the scaffold's fresh `qr-2`.

### `test_helpers/` integrity

All six queue-B agents honoured READ-ONLY. Zero edits to shared helpers; zero helper bugs reported. Each agent implemented only module-private helpers inside its own file (`_instant`/`_same_instant`, `_review_row`, `_headers_without_role`, `_mixed_class_logs`, `_open_review`, `_fail_one_matching_round`, `_restart_scoping_with_a_fresh_revision`, `_scoping_request_without_revision`, `_draft_revision_without_deliverables`). Three agents independently flagged `_instant`/`_same_instant` as the natural candidate to promote into `test_helpers/assertions.py` later.

No test was executed during Step 5 — six agents were running concurrently against the same harness and the brief barred reading `workspace/implementation/`.

## Step 7: Run Tests and Iterate — 2026-09-01T01:30:00.000Z

Orchestrator independent verification before accepting: all 8 `results.*.json` re-read directly — every round `{'passed': 344, 'total': 344, 'failed': 0}`, all eight files written within the same second (01:24), so they are one genuine sweep and not stale artifacts. Also re-checked the standing implementation constraints by grep: no `sqlite`, no file writes, no `datetime.now()`/`utcnow()` anywhere in `workspace/implementation/` (the single `json.dumps` hit is response serialization in `response.py:49`).

Subagent summary, verbatim:

---

Done — clean. Final state verified.

## 1. Rounds
**3 sweeps** (sweep 1 diagnostic; sweep 2 validated all fixes; sweep 3 confirmation, run specifically to prove the flaky connection-reset fix held rather than got lucky). A 4th sweep attempt aborted before starting — my own `pkill -f 'app.py'` matched the invoking shell's command string and killed it, leaving stale results files that I detected by their identical `api_request_id` values and discarded.

## 2. Final result
Sweeps 2 and 3 (16 rounds total) each reported, for all 8 rounds:

```
results.1..8.json   344 / 344     UNION FAILING: 0
```

## 3. Deletions
**0 deletions.** Every one of the 23 union failures traced to a verbatim-PRD-covered rule, a test-side envelope bug, or environmental load. No test failed check 1a or 1b.

## 4. Test/helper fixes
**24 occurrences across 4 test files** — one root cause, one mechanical correction.

Tests read the error identifier as `body["error"]["id"]`, a shape the API never emits, so they died with `KeyError: 'error'` before reaching their real assertion. PRD §2.2 verbatim fixes the envelope: *"All error API responses (4xx status codes) follow this standard envelope format"* with `"response_type": "error"` and `"data": { "error_id": ..., "message": ... }`. The `meta` block for errors *"contains only `api_request_id` and `api_request_timestamp`"* — there is no top-level `error` key anywhere in the contract.

Corrected `["error"]["id"]` → `["data"]["error_id"]` in:
- `test_suite/test_05_rejection_precedence_pairs.py` (3)
- `test_suite/test_06_boundary_precision.py` (2)
- `test_suite/test_07_cross_entity_state_gates.py` (10)
- `test_suite/test_08_temporal_geometry.py` (9)

These were all *negative* assertions ("the answer must not be `ERR_X`") guarding precedence ladders. The server was already answering correctly — `validate_error(...)` on the line above passed in every case; only the follow-up exclusion check crashed. So this fix changed no expectation, it just let 15 already-correct tests finish.

## 5. Implementation fixes

**`workspace/implementation/routes/engagements.py:post_valuation`** (the `VALUATION_MOVES` set)
- *Wrong*: only `UNVALUED→PROVISIONAL`, `PROVISIONAL→FINAL`, `UNVALUED→FINAL` were legal, so posting a second valuation of a *different method* on an already-`PROVISIONAL` engagement returned `ERR_INVALID_VALUATION_STATE`.
- *Corrected*: added `PROVISIONAL→PROVISIONAL` and `FINAL→FINAL`. The `g24_valuation_stage` guard was already correct and needed no change.
- *Mandate* — PRD §2.7: *"A valuation post stamps `superseded_at` on the prior non-superseded record of the same `method`, so a caller holding a stale view of the engagement's `approved_hours` would supersede a figure it never read; the guard forces a re-read first."* A same-stage re-post is therefore explicitly contemplated. PRD §2.12 item 24 enumerates the *complete* condition set — *"a `PROVISIONAL` post requires `work_status` of `IP_PROGRESS` or `SUBMITTED`, a `FINAL` post requires `HANDED_OFF`, and a `RESTATED` engagement accepts no further posts"* — and none of the three is violated here. Corroborated by §2.10 (`lifetime_valued_usd` sums `INDEPENDENT_SECTOR` records while *"records of the `MARKET_RATE` method never enter this total"*, which presumes both methods coexist on one engagement) and §4 (*"Valuation records of one engagement, both methods, including superseded ones"*). I verified `test_15::test_29` still holds, since it depends only on the `RESTATED` bar in `g24`.

**`workspace/implementation/routes/requests.py:abandon_project_request`**
- *Wrong*: abandoning from `MATCHING` released the open offer but left the pinned revision `APPROVED`, so `active_scope_revision_no` stayed non-zero.
- *Corrected*: added a `previous == "MATCHING"` branch calling the existing `domain.supersede_approved_revision(req)`.
- *Mandate* — PRD §3.3: *"A revision moves `APPROVED → SUPERSEDED` when a newer sibling reaches `APPROVED`, when the request enters `RESCOPING`, or when the request is abandoned out of `MATCHING`."* Also PRD §3.5: *"the request moves `MATCHING → ABANDONED`, the same releases run, `closed_at` is stamped and the `APPROVED` revision moves to `SUPERSEDED`."* No second edit was needed for `active_scope_revision_no`: it is derived at read time in `serialize.py` from the `APPROVED` revision, so it falls back to 0 on its own — consistent with §3.3's *"That field reads 0 whenever no revision of the request is `APPROVED`."*

**`workspace/implementation/app.py`** (`app.run(..., threaded=False)` → `threaded=True`) — infrastructure hardening, not a behaviour change; see §6.

## 6. Flakiness found
Three tests failed only intermittently, always with a transport-level error, never an assertion:
- `test_03::test_second_review_round_decides_the_conditional_outcome_to_accepted` — 5 of 8 rounds
- `test_06::test_08_exactly_the_escalated_floor_raises_the_escalation_flag` — 4 of 8 rounds
- `test_06::test_07_one_cent_of_an_hour_below_the_escalated_floor_stays_on_watch` — 1 of 8 rounds

Failure mode was `ConnectionResetError(104)` / `RemoteDisconnected`, not a bad response. All three passed deterministically when I ran them individually against a freshly booted server on a private port.

**Root cause: listen-backlog overflow from the 8× parallel harness, not an implementation defect.** I confirmed this from kernel counters sampled mid-sweep rather than inferring it: `TcpExtListenOverflows` and `TcpExtListenDrops` were both nonzero, with ~10,500 sockets in `TIME_WAIT` against a ~28k ephemeral-port range. The server answers `HTTP/1.0` with `Connection: close`, so every request burns a fresh connection; with `threaded=False`, werkzeug's accept loop blocks for the whole duration of each request, so under 8 concurrent rounds each restarting a server before all 344 tests, the accept queue overflows and the kernel resets pending SYNs.

**Eliminated by** setting `threaded=True`, which lets werkzeug accept and hand off connections instead of serializing them, draining the backlog. I first disproved the competing hypothesis (stale keep-alive sockets in the session-scoped client surviving a same-port restart) with a direct experiment: the server sends `Connection: close` on every response, so no socket is ever pooled across a restart. The resets disappeared across all 16 rounds of sweeps 2 and 3.

This does not weaken the concurrency guarantees: the client is a single sequential pytest process, so request handling remains effectively serial, and the three conservation invariants are read-derived rather than stored (verified in `serialize.py` — `slots_committed`/`slots_reserved`/`slots_available`/`utilization_ratio`/`posture` from `metrics`, `hours_committed`/`hours_remaining` from `metrics`, `lifetime_valued_usd` via `calc.lifetime_valued_usd()`), so no compensating write can drift them regardless of threading.

## 7. Residual concerns
- **`FINAL→FINAL` is slightly beyond what any test exercises.** I added it alongside the test-required `PROVISIONAL→PROVISIONAL` for symmetry, on the strength of the same §2.7 sentence. Nothing in the suite covers it either way. A stricter reading of §3.9's *"Three forward moves exist"* could argue for admitting only `PROVISIONAL→PROVISIONAL`; I judged that sentence to be enumerating advances of the status dimension, not the legality of same-stage re-posts, which §2.7 addresses directly. This is the one place I resolved by judgement.
- **`threaded=True` is an environmental mitigation, not a guarantee.** At substantially higher parallelism than 8, backlog overflow could resurface, since the underlying pressure is the harness's connection-per-request restart pattern and the ~28k ephemeral-port ceiling. The 3 affected tests are fair and correctly built; nothing about them is fragile in itself.
- **`g24_valuation_stage` returns `"FINAL"` whenever `work_status` is `HANDED_OFF`** without itself checking the *"no prior valuation record"* clause of `UNVALUED → FINAL`; that clause is enforced separately at the call site in `post_valuation`. Behaviour is correct, but the rule is split across two places, which is worth knowing if that path is edited later.
- I did not read `SCAFFOLD*.yaml`, `worklog.md`, or any sibling task directory, per the read restrictions. All adjudication above is against `workspace/PRD.md` only.

## Step 8: Finalize PRD — align documentation to implementation — 2026-09-01T02:05:00.000Z

Step 8 ran (not skipped): Step 7 took 3 sweeps and made 2 behavioural `implementation/` fixes plus 24 test-side corrections, so the zero-iteration skip condition did not apply.

Orchestrator verification before accepting: `PRD_FINALIZED.md` is 482 lines (identical count to `PRD.md`), ends on the §5 error table (`ERR_SCOPE_BREACH_THRESHOLD | 409`) so it is not truncated, retains all 29 markdown headers, and a whitespace-normalized diff against `PRD.md` shows exactly 4 changed lines = 2 in-paragraph edits. Matches the subagent's claim.

Subagent summary, verbatim:

---

Done. `PRD_FINALIZED.md` written with two edits.

## Size delta
- `PRD.md`: 482 lines / 16,065 words / 117,724 bytes
- `PRD_FINALIZED.md`: 482 lines / 16,217 words / 118,737 bytes
- **Line delta: 0 (0.00%)** — both edits are in-paragraph prose insertions. Word delta +152 (+0.95%); byte delta +1,013 (+0.86%).

## Changes

- **§3.9 (valuation dimension) — insert — same-stage valuation re-posts are legal, and the stage is derived from `work_status` rather than named by the caller** — `implementation/routes/engagements.py:736-745` (`VALUATION_MOVES`), `:756-762` (pair check + `UNVALUED→FINAL` prior-record bar), `implementation/guards.py:337-353` (`g24_valuation_stage`).
  Inserted after the `UNVALUED → FINAL` sentence: the stage is fixed by `work_status` (`HANDED_OFF`→`FINAL`, `IN_PROGRESS`/`SUBMITTED`→`PROVISIONAL`); `PROVISIONAL → PROVISIONAL` and `FINAL → FINAL` are both accepted as re-posts, each leaving `valuation_status` where it is while still writing a record and stamping `superseded_at` on the prior non-superseded record of the same `method`; those two plus the three forward moves are the **complete** set of legal `(current, stage)` pairings and any other pairing is refused. The pre-existing sentences ("Three forward moves exist", the three move conditions, the `RESTATED`/`FINAL`-stage refusal sentence) are left verbatim.

- **§3.3 (abandoning a request) — insert — abandonment out of `MATCHING` supersedes the `APPROVED` revision** — `implementation/routes/requests.py:366-370`, `implementation/domain.py:14-18` (`supersede_approved_revision`), `implementation/serialize.py:57-62 / :82` (`active_scope_revision_no` derivation).
  Inserted between the DRAFT/MATCHING offer-release sentence and the SCOPING/SCOPED sentence: abandonment from `MATCHING` also moves the request's `APPROVED` revision, when it has one, to `SUPERSEDED`, so `active_scope_revision_no` falls back to 0, and `DRAFT` revisions are left alone.

## Per-edit pre-edit search log

**Edit 1 — subject: which `(valuation_status, reached stage)` pairs a valuation post admits, and how the stage is determined.**
(b) Impl paths enumerated / read: `routes/engagements.py:736-770` (`VALUATION_MOVES`, `post_valuation`, incl. the `UNVALUED`+`FINAL`+`existing` bar, guard order g24-before-g30, `variant_label = stage`, `valuation_status = stage`, `S.touch` version bump); `routes/engagements.py:773-777` (`list_valuation_records`, both methods incl. superseded); `guards.py:337-353` (`g24_valuation_stage`: `RESTATED`→refuse, `HANDED_OFF`→`FINAL`, `IN_PROGRESS`/`SUBMITTED`+≥1 approved log→`PROVISIONAL`, else refuse — so `NOT_STARTED`/`ACCEPTED`/`TERMINATED` refuse); `domain.py:145-164` (`post_valuation_record`, per-method `sequence_no`), `:167-173` (`supersede_records`, optional method filter), `:176-191` (`restate_valuation`: requires a live record **and** status in `PROVISIONAL`/`FINAL`, supersedes **all** methods, posts `INDEPENDENT_SECTOR`/`RESTATED`), `:235` (termination cascade callsite); `calc.py:447-494` (`approved_logs`, `valuation_amounts`, overhead tiers), `calc.py:497-513` (`lifetime_valued_usd`); `serialize.py:149` (`lifetime_valued_usd` exposure), `serialize.py:224` (`valuation_status`), `serialize.py:342-359` (`valuation_record`). Also grepped every writer of `valuation_status` (only `post_valuation` and `restate_valuation`) and every writer of `time_logs["approved"]` (`engagements.py:334`, `:521` — only ever flips to `True`, never back, and there is no row-delete path).
(c) Wording adjustments made: (i) I did **not** re-scope the "at least one child time log to be `approved`" clause onto all `PROVISIONAL`-stage posts even though `g24` enforces it there, because `approved` is monotone so the clause is vacuously satisfied on a `PROVISIONAL → PROVISIONAL` re-post — restating it would have been a false narrowing risk with no behavioural payoff. (ii) I deliberately said "any other pairing is refused" rather than enumerating illegal pairings, after confirming exactly 5 pairings are reachable in impl (`UNVALUED/PROVISIONAL`, `UNVALUED/FINAL`, `PROVISIONAL/PROVISIONAL`, `PROVISIONAL/FINAL`, `FINAL/FINAL`) — `FINAL` + a `PROVISIONAL` stage is unreachable because `HANDED_OFF` is terminal, so the universal claim is safe. (iii) I said "stamping `superseded_at` on the prior non-superseded record of the same `method`" (matching `supersede_records(..., method=method)`) and avoided any wording implying the re-post supersedes across methods, which would have contradicted `post_valuation:765` while colliding with the method-less `supersede_records` call inside `restate_valuation`. (iv) I did **not** touch §2.12 item 24 or §3.9's `RESTATED`/`FINAL`-stage refusal sentence — item 24's enumeration is already consistent with the impl (it bars nothing about same-stage re-posts) and already covers `ACCEPTED`/`TERMINATED` refusals by implication.

**Edit 2 — subject: the abandonment cascade's effect on scope revisions and `active_scope_revision_no`.**
(b) Impl paths enumerated / read: `routes/requests.py:353-376` (`abandon_project_request`: status/`closed_at` stamped **before** the offer withdrawal, `withdraw_open_offers_of_request(..., "ADMIN", bump_failed=False)` for `DRAFT`/`MATCHING`, `supersede_approved_revision` for `MATCHING`, `DRAFT`|`APPROVED`→`WITHDRAWN` for `SCOPING`/`SCOPED`); `domain.py:14-18` (`supersede_approved_revision` — loops all `APPROVED` revisions of the request); every other callsite of that helper: `routes/requests.py:268` (approval superseding a prior sibling), `domain.py:81` (`MATCHING → RESCOPING` branch), `domain.py:87` (`MATCHING → ABANDONED` counter branch), `routes/engagements.py:350` (breached hold → `IN_DELIVERY → RESCOPING`), `routes/engagements.py:462` (`RESCOPE_REQUIRED` change → `IN_DELIVERY → RESCOPING`); `domain.py:52-89` (`release_offer` / `resolve_request_after_release` — early-returns unless status is `MATCHING`, so the already-`ABANDONED` request is not re-resolved and `failed_match_rounds` is not bumped); `domain.py:92-97` (`withdraw_open_offers_of_request`); `serialize.py:57-62` + `:82` (`active_scope_revision_no` = max `revision_no` over `APPROVED` revisions, 0 when none — derived at read time, never stored).
(c) Wording adjustments made: (i) "when it has one" added so the sentence does not assert an `APPROVED` revision always exists (the helper is a no-op loop otherwise). (ii) "falls back to 0" rather than "resets to 0" / "is recomputed", because the field is derived in `serialize.py` and never assigned. (iii) Added "the request's `DRAFT` revisions, if any, are left where they are", because the `MATCHING` branch does not call `withdraw_draft_revisions` — without it, the adjacent `SCOPING`/`SCOPED` sentence invited an implementer to generalise `DRAFT`→`WITHDRAWN` to the `MATCHING` case. (iv) I said nothing about `withdraw_reason` or `failed_match_rounds` on the abandonment path, keeping the edit inside the Step 7 subject and out of the §3.5 release-branch prose that already governs them.

## Step 7 items that required NO PRD edit

- **Test/helper fixes (24 occurrences of `["error"]["id"]` → `["data"]["error_id"]` across `test_05`, `test_06`, `test_07`, `test_08`).** Pure fixture bug. PRD §2.2's error envelope (`response_type: "error"`, `data.error_id` / `data.message`, `meta` limited to `api_request_id` + `api_request_timestamp`) is verbatim correct and exactly what `implementation/response.py:82-88` emits — I verified `error_response` field by field. There is no top-level `error` key anywhere in the impl. No PRD surface; prose kept verbatim.
- **`app.py` `threaded=False` → `threaded=True`.** Pure infrastructure/transport hardening for the 8× parallel harness (listen-backlog overflow producing `ConnectionResetError(104)`). No observable API behaviour, no PRD surface — the PRD never speaks about the WSGI server, concurrency, or process model. No edit.
- **Deletions: none**, so nothing to reflect.
- **Residual concern "`g24_valuation_stage` splits the `UNVALUED → FINAL` no-prior-record clause across guard and callsite".** Implementation-structure observation only; the composed behaviour equals PRD §3.9's existing sentence, which I left verbatim. No edit.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-01T02:35:00.000Z

Orchestrator verification before accepting: `PRD_COMPLETED.md` is 482 lines / 132,515 chars, ends on the §5 error table (`ERR_SCOPE_BREACH_THRESHOLD | 409`) so it is not truncated, retains all 29 markdown headers, and both structural tables are intact — 66 endpoint rows and 56 error rows, identical to `PRD_FINALIZED.md`. Separately confirmed that every file under `workspace/implementation/` has an mtime at or before 01:04, i.e. earlier than the 01:24 all-green Step 7 sweep, so Steps 8 and 9 changed documentation only and the 344/344 × 8-round result still describes the shipped code.

Subagent summary, verbatim:

---

Done. `PRD_COMPLETED.md` is complete.

## Exit summary

**Files.** Source `workspace/PRD_FINALIZED.md`: 482 lines / 118,737 chars. Result `PRD_COMPLETED.md`: 482 lines / 132,515 chars (**char delta +13,778**). Line count identical — every change is an in-paragraph insert or revision; no new paragraphs, no new sections, no table rows added or removed (§4 still 66 rows, §5 still 56 rows).

**Counts.** 57 changes total: **43 ambiguity-pins**, **14 mismatch-revisions**.

**Changes** (`{section} — {kind} — {class} — {what} — {impl}`)

- §2.1 — insert — ambiguity — 404/405 are answered by the router before the header checks, so they need no headers; trailing slash ignored — `app.py:38-57`, `app.py:27`
- §2.2 — insert — ambiguity — `request_id` is `req_` + exactly 20 upper-case-letter/digit chars — `response.py:13,22`
- §2.2 — insert — ambiguity — `_meta` timestamp reads the logical clock, not wall time — `response.py:38`
- §2.3 — insert — ambiguity — non-integer pagination → `ERR_INVALID_PAGINATION`, empty string → default, validated on every list endpoint; insertion order breaks `created_at` ties — `response.py:91-100,119`, `store.py:120`
- §2.3 — revise — mismatch — filters are exact string equality, empty ignored; `supersedes_scope_id` is one link, not a forward chain walk; engagement filter axes corrected to include `match_offer_id`, `work_status`, `valuation_status`, `quality_gate` — `routes/requests.py:196-201`, `routes/engagements.py:36-46`, `routes/offers.py:32-42`
- §2.4 — revise — mismatch — corrected which writes bump `version` (deliverable→scope; agreement/time-log/hold/auto-approved change→engagement) and which do not (milestone, review, survey, `MANAGER_REVIEW` change) — `routes/requests.py:243`, `routes/engagements.py:139,262-286,386,351,464`
- §2.8 — insert — ambiguity — the five capacity figures are derived at read time, never stored, and recomputing them does not advance `version` — `serialize.py:37`, `calc.py`
- §2.9 — insert — ambiguity — window hours and derived `status` are computed at read time from live rows — `calc.py:89`
- §2.10 — insert — ambiguity — `lifetime_valued_usd`, both reliability variants and both counts are derived at read time — `serialize.py:130`
- §2.12 item 18 — insert — ambiguity — pagination guard applies to every declared list endpoint — `response.py:119`
- §2.12 item 19 — insert — ambiguity — a deliverable's `hours_estimate` is also under the zero-hours guard — `routes/requests.py:222-223`, `guards.py:309`
- §2.12 item 20 — insert — ambiguity — scope approve requires the owning request in `SCOPING` — `routes/requests.py:262`
- §2.12 item 24 — revise — mismatch — `PROVISIONAL` requires ≥1 approved log; any other work status is refused outright — `guards.py:337`
- §2.12 item 31 — insert — ambiguity — submit-for-scoping and match need the stricter `ACTIVE`, so `PROBATION` is refused there — `guards.py:392,397`
- §2.12 item 49 — insert — ambiguity — the approved-revision guard also runs on match — `routes/requests.py:294`, `guards.py:575`
- §2.12 item 50 — insert — ambiguity — re-scope limit is checked on `RESCOPE_REQUIRED` change creation, before the row is written — `routes/engagements.py:410-464`, `guards.py:580`
- §2.12 item 55 — insert — ambiguity — window-hours guard also on `AUTO_APPROVABLE` change creation, before insert — `routes/engagements.py:410-464`, `guards.py:609`
- §3.1 — insert — ambiguity — `contact_email` 1..320, unique, duplicate → `ERR_VALIDATION`, no format check — `routes/partners.py:17-40`
- §3.1 — insert — ambiguity — partner summary = partner row + `survey_composite_scores` + `surveys` + `eligible_survey_count`, all surveys listed regardless of eligibility — `serialize.py:361`
- §3.1 — insert — ambiguity — `probation_reason` defaults `MANUAL`, `ACTIVE` clears it, writing against an already-`SUSPENDED` partner → `ERR_PARTNER_SUSPENDED`; suspension cascade stamps `closed_at`, leaves revisions alone, does not bump `failed_match_rounds` — `routes/partners.py:71-90`, `domain.py:262`
- §3.1 — insert — ambiguity — `cycle_code` 1..64, interval judged before duplicate code, both → `ERR_VALIDATION`; new cycle gets `recalc_epoch` 0 and null `last_recalculated_at` — `routes/cycles.py:18-40`
- §3.1 — revise — mismatch — the neglect step only considers engagements in `IN_PROGRESS` — `domain.py:310`
- §3.2 — insert — ambiguity — volunteer `email` 1..320, unique, duplicate → `ERR_VALIDATION` — `routes/volunteers.py:31-63`
- §3.2 — insert — ambiguity — vetting clears `pause_reason`, requires `PENDING_VETTING` (`ERR_VOLUNTEER_NOT_ACTIVE`), and validates `verify_skill_codes` as a list of strings before the state check — `routes/volunteers.py:73-92`
- §3.2 — revise — mismatch — window status precedence is `EXPIRED` first, then `EXHAUSTED` (remaining ≤ 0), else `OPEN` — `calc.py:89-108`
- §3.2 — insert — ambiguity — `to_status` enum is the three values; `PENDING_VETTING` → `ERR_VALIDATION`, un-vetted volunteer → `ERR_CREDENTIAL_NOT_VERIFIED`, out of `DEACTIVATED` → `ERR_VOLUNTEER_NOT_ACTIVE`; `pause_reason` defaults `ADMIN`, cleared on `ACTIVE` — `routes/volunteers.py:96-117`
- §3.3 — insert — ambiguity — `required_skill_code` is 2..32 chars, compared literally, no character-set rule — `routes/requests.py:54`
- §3.3 — insert — ambiguity — submitting after the cycle's `ends_at` → `ERR_INVALID_REQUEST_STATE` — `routes/requests.py:115-116`
- §3.3 — revise — mismatch — `deliverable_count` counts only non-`WAIVED` children, and each addition bumps the revision's `version` — `serialize.py:92,105`, `routes/requests.py:243`
- §3.3 — insert — ambiguity — abandon's `reason` is validated (≤500) but stored nowhere; releases carry `ADMIN` and bump nothing — `routes/requests.py:356,365`
- §3.4 — insert — ambiguity — a request with no `APPROVED` revision → `ERR_SCOPE_VERSION_SUPERSEDED` — `guards.py:575`
- §3.4 — insert — ambiguity — window selection final tie-break is insertion order; only the volunteer's best-scoring claim is carried forward — `calc.py:153,196`
- §3.4 — insert — ambiguity — candidate ordering ends in insertion order — `calc.py:196`
- §3.5 — revise — mismatch — a fresh engagement reads `scope_creep_pct` -1.0000 (not 0) with level `NONE` — `calc.py:323-328`
- §3.5 — insert — ambiguity — a withdrawal omitting the reason leaves `withdraw_reason` null and still raises the counter; a cascade reaching an offer after its request left `MATCHING` only releases hours and slot — `routes/offers.py:122-135`, `domain.py:69,92`
- §3.6 — revise — mismatch — `ip_disposition`/`confidentiality_tier` are optional and default from the pinned revision; `indemnity_cap_usd` is required — `routes/engagements.py:93-140`
- §3.6 — insert — ambiguity — same-party counter leaves document and engagement untouched, unlike allowance exhaustion — `guards.py:446`
- §3.6 — revise — mismatch — the counter-limit void moves the row from `SENT`, not `COUNTERED` — `routes/engagements.py:168-200`
- §3.6 — insert — ambiguity — executing twice as the same party → `ERR_INVALID_AGREEMENT_STATE` — `routes/engagements.py:204-221`
- §3.6 — insert — ambiguity — supplied `void_reason` is validated then overwritten with `TERMS_REJECTED`; termination only if the engagement is still live; *governing agreement* = newest non-`VOIDED`, else newest overall — `routes/engagements.py:225-236`, `guards.py:429`
- §3.7 — insert — ambiguity — milestone scheduling has no work-state gate and leaves the engagement's `version` untouched — `routes/engagements.py:262-286`
- §3.7 — insert — ambiguity — a hold more than 24h early → `ERR_VALIDATION` after the state checks; a breach supersedes the approved revision without consuming a re-scope allowance — `routes/engagements.py:316-352`
- §3.7 — insert — ambiguity — auto-approval stamps `decided_by_user_id`/`decided_at`; escalation supersedes the revision; the limit check precedes the insert — `routes/engagements.py:410-464`
- §3.7 — insert — ambiguity — `resulting_scope_revision_no` is filled when the next revision is drafted — `domain.py:30`, `routes/requests.py:179`
- §3.8 — revise — mismatch — submit has four preconditions, requires no per-deliverable hours coverage, and a missing held check-in → `ERR_INVALID_WORK_STATE` — `routes/engagements.py:503-525`
- §3.8 — insert — ambiguity — the highest-numbered round is consulted; any other status → `ERR_REVIEW_NOT_SCORED` — `routes/engagements.py:537-566`
- §3.8 — insert — ambiguity — `request_rework` optional/false; unavailable rework → `ERR_REVIEW_NOT_SCORED` — `routes/engagements.py:627-657`
- §3.8 — revise — mismatch — handoff enforces both IP disposition and tier-ordering alignment; `destruction_certificate_ref` is stored but omitted from the representation — `routes/engagements.py:687-714`, `guards.py:420`, `serialize.py:208`
- §3.9 — insert — ambiguity — terminate's reason defaults to `ADMIN` — `routes/engagements.py:720-730`
- §3.9 — revise — mismatch — termination voids *every* `DRAFTED`/`SENT`/`COUNTERED` agreement, not just the governing one — `domain.py:216-233`
- §3.9 — insert — ambiguity — a survey needs `HANDED_OFF` or `TERMINATED`, else `ERR_INVALID_WORK_STATE` — `routes/engagements.py:789`
- §4 preamble — insert — ambiguity — pinned which row each multi-row operation returns (match→offer 201, accept→engagement 201, valuation→record 201, agreement issue→agreement 201, hold→milestone, decide→change request, review→review, clock→`{}`, etc.) — `routes/offers.py:104`, `routes/requests.py:334`, `routes/engagements.py:352,496,657,770`, `routes/cycles.py:81`
- §4 `GET /scope-definitions` — revise — mismatch — single-link equality filter, not a forward chain walk — `routes/requests.py:198-199`
- §4 `GET /milestones/{id}/time-logs` — insert — ambiguity — ascending work-date order — `routes/engagements.py:311`
- §4 `GET /engagements/{id}/quality-reviews` — insert — ambiguity — ascending `round_no` — `routes/engagements.py:583`
- §4 `GET /engagements/{id}/satisfaction-surveys` — insert — ambiguity — oldest submission first, opposite of the partner-level listing — `routes/engagements.py:832` vs `routes/partners.py:102`
- §5 preamble — revise — mismatch — the table covers rejections from declared endpoints; `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405) and `ERR_INTERNAL` (500) are framework-level and sit outside it — `errors.py:61-63`, `app.py:49-63`

**Coverage.** All 15 implementation modules were read end to end (`app.py`, `config.py`, `errors.py`, `response.py`, `store.py`, `calc.py`, `guards.py`, `domain.py`, `serialize.py`, and all six route modules), and every edit above cites a line I re-verified. Honest gaps: (1) `test_helpers/` and `test_suite/` were never opened — permitted but explicitly non-authoritative, so no test-derived claim entered the document; (2) numeric constant tables in `config.py` (TTL hours, thresholds, tier bands, weights) were cross-checked only where PRD prose already named them, so if a constant is stated nowhere in the PRD it remains unstated rather than newly pinned; (3) the §2.12 ladder's 57 rungs were verified for the rungs I edited and spot-checked elsewhere, not re-walked rung by rung against `guards.py` ordering; (4) process note — I read the implementation files before beginning edits rather than strictly interleaving file-by-file, though all edits landed with per-line verification. The two pre-existing `PRD_FINALIZED.md` edits (§3.9 same-stage valuation re-posts, §3.3 abandonment out of `MATCHING`) were left intact and no edit contradicts them; no genuine implementation inconsistency with either was found.

## Step 9b: Gap closure — §2.12 ladder rung-by-rung walk + config.py constant audit — 2026-09-01T03:00:00.000Z

Step 9's own agent honestly reported two open gaps against its stated "zero remaining PRD silence" objective: (a) only 8 of the 57 §2.12 ladder rungs were verified rung-by-rung against `guards.py`, the rest spot-checked; (b) `config.py` constants not already named in PRD prose were left unstated. The ladder is the highest-value correctness surface in this task — 57 priority-ordered validations whose relative order every precedence test depends on — so the orchestrator dispatched one focused agent to close both. It edited `PRD_COMPLETED.md` in place, was barred from touching `workspace/implementation/`, and was barred from reading tests, scaffolds, worklog, `PRD.md`, and `PRD_FINALIZED.md`.

Orchestrator verification: `PRD_COMPLETED.md` now 482 lines / 133,994 chars — still zero net line change from `PRD_FINALIZED.md`, still 66 endpoint rows / 56 error rows / 29 headers, still ending on `ERR_SCOPE_BREACH_THRESHOLD | 409` (not truncated). Latest mtime anywhere under `workspace/implementation/` remains 09-01 01:04, still earlier than the 01:24 all-green sweep, so the implementation is untouched and the 344/344 × 8-round result continues to describe the shipped code.

Subagent summary, verbatim:

---

Both remaining Gap A edits are applied and Gap B is closed. Final report:

## Counts

| | lines (`wc -l`) | chars (`wc -c`) |
|---|---|---|
| before | 482 | 132515 |
| after | 482 | 133994 |

Zero net line change (all five edits are in-paragraph); +1479 chars. No sections, paragraphs, §4 rows (66) or §5 rows (56) added or removed.

## Gap A — all 57 rungs walked

`impl` = `workspace/implementation`. "ordering verified" = every route module where the guard is reachable was checked for callsite order against lower/higher rungs that also apply there.

| rung | guard fn | err id matches | condition matches | ordering verified on | verdict |
|---|---|---|---|---|---|
| 1 | `g01_auth_headers` | yes | yes | `app.py:41` `before_request`, all endpoints | pinned |
| 2 | `g02_role_permitted` | yes | yes (`ALL_ROLES` unknown-role test then per-endpoint tuple) | `app.py:42`, all endpoints via `ROLE_REGISTRY` | pinned |
| 3 | `g03_partner` | yes | yes | partners.py 2 sites, volunteers.py n/a | pinned |
| 4 | `g04_cycle` | yes | **no — PRD named 2 of 3 endpoints** | cycles.py:70 (`/engagements` list) was undocumented | **REVISED** |
| 5 | `g05_request` | yes | yes | requests.py 7 sites | pinned |
| 6 | `g06_scope` | yes | yes | requests.py 4 sites | pinned |
| 7 | `g07_volunteer` | yes | yes | volunteers.py 5 sites | pinned |
| 8 | `g08_offer` | yes | yes | offers.py 4 sites | pinned |
| 9 | `g09_engagement` | yes | yes | engagements.py 12 sites | pinned |
| 10 | `g10_agreement` | yes | yes | engagements.py 4 sites | pinned |
| 11 | `g11_milestone` | yes | yes | engagements.py 3 sites | pinned |
| 12 | `g12_scope_change` | yes | yes | engagements.py 2 sites | pinned |
| 13 | `g13_review` | yes | yes | engagements.py 3 sites | pinned |
| 14 | `g14_body_*` / `g14_deliverable_ids` | yes (per-FK 404 ids) | **no — 2 of 4 sites missing** | requests.py:44,48,137; engagements.py:594 | **REVISED** |
| 15 | `g15_owns_*` | yes | yes | requests.py:110,261; offers.py:50,110; engagements.py:171 + | pinned |
| 16 | `g16_review_open` / `g16_review_act` | yes | **no — score endpoint + the two-test shape missing** | engagements.py:~560, 596, 630 | **REVISED** |
| 17 | `v_str/v_enum/v_num/v_int/v_bool/v_dt/v_id` (guards.py 190–308) | yes | yes | every write handler | pinned |
| 18 | `response.paginate` | yes | yes (validated at end of list handlers, after rungs 3–13 — matches numbering) | all 12 list endpoints | pinned |
| 19 | `g19_positive` | yes | yes (fires only when `dec(value) == 0`; negatives are rung 17) | requests.py:152,222,223; engagements.py | pinned |
| 20 | `g20_request_state` | yes | yes | requests.py:111,153,262,286,342,358 | pinned |
| 21 | `g21_scope_draft` | yes | yes | requests.py:224,263 | pinned |
| 22 | `g22_offer_open` | yes | yes | offers.py:58,113,128 | pinned |
| 23 | `g23_work_state` | yes | **no — 3 endpoints + the held-check-in interaction missing** | engagements.py:155,604,633,508/514 + 7 others | **REVISED** |
| 24 | `g24_valuation_stage` | yes | yes (FINAL/PROVISIONAL derivation) | engagements.py:756 | pinned |
| 25 | `g25_agreement_state` | yes | yes | engagements.py:180 + send/execute | pinned |
| 26 | `g26_milestone_scheduled` | yes | yes | engagements.py hold/complete | pinned |
| 27 | `g27_review_state` | yes | yes | engagements.py:597,634 | pinned |
| 28 | `g28_scope_change_pending` | yes | yes | engagements.py 2 sites | pinned |
| 29 | `g29_request_version` | yes | yes | requests.py:154 | pinned |
| 30 | `g30_engagement_version` | yes | yes | engagements.py:763 + | pinned |
| 31 | `g31_partner_not_suspended` / `g31_partner_active` | yes | yes | requests.py:59,113,265,288; offers.py:59 | pinned |
| 32 | `g32_credential_verified` | yes | yes | offers.py:60 | pinned |
| 33 | `g33_volunteer_active` | yes | yes | offers.py:61 | pinned |
| 34 | `g34_attestation` | yes | yes | engagements.py:696 | pinned |
| 35 | `g35_ip_terms` | yes | yes | engagements.py:697 | pinned |
| 36 | `g36_agreement_executed` | yes | yes (`governing_agreement` = newest non-VOIDED else newest) | engagements.py start | pinned |
| 37 | `g37_counter_limit` | yes | **no — allowance-vs-party precedence unstated** | engagements.py:182–188 | **REVISED** |
| 38 | `g38_offer_not_expired` | yes | yes | offers.py:62,114 | pinned |
| 39 | `g39_window_inside_cycle` | yes | yes | volunteers.py:177 | pinned |
| 40 | `g40_milestone_due` | yes | yes | engagements.py milestone create | pinned |
| 41 | `g41_log_inside_window` | yes | yes | engagements.py time-logs | pinned |
| 42 | `g42_no_clock_regression` | yes | yes | cycles.py clock advance | pinned |
| 43 | `g43_no_window_overlap` | yes | yes | volunteers.py:179 | pinned |
| 44 | `g44_milestone_spacing` | yes | yes (closed 72h buffer) | engagements.py milestone create | pinned |
| 45 | `g45_checkin_saturation` | yes | yes (limit 2 in rolling fortnight; ±7 days hardcoded) | engagements.py milestone create | pinned |
| 46 | `g46_unique_skill` | yes | yes | volunteers.py:103–106 | pinned |
| 47 | `g47_unique_sequence` / `_weight_ceiling` / `_weight_exact` | yes | yes | requests.py:225,226,266 | pinned |
| 48 | `g48_deliverable_set` | yes | yes | engagements.py:606 | pinned |
| 49 | `g49_scope_approved` | yes | yes | requests.py:294; offers.py:63; engagements.py:699 | pinned |
| 50 | `g50_rescope_limit` | yes | yes (`MAX_RESCOPES` = 3, left as-is per instruction) | requests.py:343 | pinned |
| 51 | `g51_cycle_not_frozen` | yes | yes | requests.py:297; offers.py:64 | pinned |
| 52 | `g52_restricted_urgency` | yes | yes | requests.py:298 | pinned |
| 53 | `g53_partner_engagement_limit` | yes | yes | requests.py:299; offers.py:65 | pinned |
| 54 | `g54_volunteer_concurrency` | yes | yes (limit 2) | offers.py:66 | pinned |
| 55 | `g55_window_hours` / `g55_log_hours` | yes | yes | requests.py:310; engagements.py time-logs | pinned |
| 56 | `g56_no_breach` | yes | yes (BREACH creep **or** any PENDING/ESCALATED child SCR) | engagements.py:508 (before the 514 held-check-in test) | pinned |
| 57 | `g57_candidates` | yes | yes in prose; **guard is dead code** — match raises inline at requests.py:302–306 | requests.py:301–306 | pinned, no edit (see bugs below) |

Ordering was verified in-order on every endpoint where two or more rungs coexist; I found **no** case of a lower-numbered guard invoked after a higher-numbered one, with the single documented exception folded into the rung-23 edit (submit's held-check-in `ERR_INVALID_WORK_STATE` is deliberately tested *after* rung 56, engagements.py:508 vs 514).

## Gap A edits (5 total)

- §2.12 item 4 — revise — mismatch — added the third `g04_cycle` site (`GET /program-cycles/{id}/engagements`) to the endpoint list — `impl/routes/cycles.py:70`
- §2.12 item 14 — revise — mismatch — added the `supersedes_scope_id` FK site (with its precedence over that endpoint's own schema/positive-quantity/from-set/stale-version checks) and the `deliverable_id` FK site — `impl/routes/requests.py:135–137`, `impl/routes/engagements.py:594`
- §2.12 item 16 — revise — mismatch — added `POST /quality-reviews/{id}/score` and spelled out that both acts against an existing round apply the same pair of tests (scope author barred; any operator other than `reviewer_user_id` barred), judged ahead of payload/review-status/deliverable-set checks — `impl/guards.py:183–189`, `impl/routes/engagements.py:594–606, 630–634`
- §2.12 item 23 — revise — mismatch — added `POST /agreements/{id}/send` (`NOT_STARTED`), `POST /quality-reviews/{id}/score` and `/decide` (`SUBMITTED`) to the from-set narrative and endpoint list, and pinned that submit's held-check-in requirement answers the same identifier but runs after rung 56 — `impl/routes/engagements.py:155, 508, 514, 604, 633`
- §2.12 item 37 — revise — mismatch — pinned that the allowance is judged before the party, so a same-party counter at `counter_round == 3` voids-and-terminates rather than being harmlessly refused — `impl/guards.py:446–451`, `impl/routes/engagements.py:182–188`

I did not touch the two protected passages (§3.9 same-stage valuation re-posts / work-status-derived stage; §3.3 abandonment-out-of-`MATCHING` superseding). Both read as consistent with `impl/routes/requests.py:364–375` and `impl/domain.py`.

## Gap B — every `config.py` constant (90 top-level names)

**Verdict: zero inserts.** Every constant that is observable through the API already has its value stated in PRD prose; I verified each by literal grep of the value against `PRD_COMPLETED.md` and by reading the surrounding passage.

Already-stated (observable, value present): all enumeration tuples (`ROLE_*`, `DISCIPLINES`, `URGENCIES`, `CONFIDENTIALITY_TIERS`, `IP_DISPOSITIONS`, `DECLINE_REASONS`, `WITHDRAW_REASONS`, `WORK_STATUSES`, `VALUATION_STATUSES`, `REVIEW_*`, `MILESTONE_*`, `SCR_*`, `TIME_CLASSES`, `SENIORITIES`, statuses) — surfaced in §3/§4/§5; `CAPACITY_TIERS` (250000/2000000/10000000 → MICRO/SMALL/MID/LARGE, slots 1/2/4/6); `SKILL_TIER_WEIGHT` (0.20/0.45/0.70/0.88/1.00); `VERIFIED_SKILL_BONUS` 0.05; `URGENCY_AVAILABILITY_WEIGHT` (0.20/0.30/0.45); `RELIABILITY_WEIGHT` 0.25; `SHORTFALL_PENALTY_PER_HOUR` 0.004; `SHORTFALL_PENALTY_CAP` 0.30; `SENIORITY_MULTIPLIER` (0.90/1.00/1.08/1.12); `VOLUNTEER_MAX_CONCURRENT` 2; `OFFER_TTL_HOURS` (120/72/24); `INDEPENDENT_SECTOR_RATE_USD` 34.79; `MARKET_RATE_CAP_USD` (180/320/480/650); `CLASS_FACTOR` (1.00/0.50/0.00); `OVERHEAD_TIERS` (2500→0.12, 10000→0.09, else 0.06); `ADMIN_OVERHEAD_MIN_USD` 45.00; `DECAY_LAMBDA` 0.85; `DECAY_WINDOW_N` 8; `MISSED_CHECKIN_PENALTY` 0.10; `RELIABILITY_BASELINE` 0.7500; `RELIABILITY_FLOOR` 0.4000; `SCORE_SCALE` 20; `PASS_THRESHOLD` 78.00; `CONDITIONAL_THRESHOLD` 60.00; `CREEP_WATCH/ESCALATED/BREACH` 0.1500/0.3000/0.5000; `POSTURE_RESTRICTED_AT` 0.8000; `POSTURE_FROZEN_AT` 1.0000; `SATISFACTION_WEIGHTS` (0.40/0.35/0.25); `RECENCY_WEIGHTS` (0.34/0.26/0.18/0.13/0.09); `SATISFACTION_SAMPLE_MAX` 5; `PROBATION_MIN_SAMPLE` 3; `PROBATION_CEILING` 55.00; `RECOVERY_FLOOR` 70.00; `MAX_RESCOPES` 3; `MAX_FAILED_MATCH_ROUNDS` 2; `MAX_COUNTER_ROUNDS` 3; `MILESTONE_MIN_SPACING_HOURS` 72; `CHECKIN_SATURATION_LIMIT` 2; `MILESTONE_GRACE_HOURS` 24; `MISSED_CHECKIN_TERMINATION_THRESHOLD` 2; `REWORK_DEADLINE_HOURS` 168; `CLOCK_START_ISO` 2026-08-01T00:00:00Z.

Deliberately unstated because unobservable: `PORT` default 10000 (`app.py:72`, process plumbing only); `D` (the `Decimal` alias, not a behavioural constant); and three constants that are **defined but never read by any code path**, so no API response depends on them — `MILESTONE_SATURATION_WINDOW_DAYS` 14, `MILESTONE_EARLY_HOLD_HOURS` 24, `MAX_REVIEW_ROUNDS` 2. (The equivalent numbers happen to appear in prose anyway, sourced from the behaviour that is hardcoded: `g45` uses a literal ±7-day sweep, hold uses `MILESTONE_GRACE_HOURS`, decide compares `>= 2` inline. I left the prose alone since it describes the observed behaviour correctly.) Also unreachable: `MILESTONE_WAIVER_REASONS`' `"ADMIN"` member is never produced by any handler.

## Implementation observations — found, reported, NOT fixed

1. `guards.py:633 g57_candidates` is **dead code**. `POST /project-requests/{id}/match` raises `ERR_NO_ELIGIBLE_VOLUNTEER` inline at `routes/requests.py:302–306` after charging `failed_match_rounds`. Behaviourally identical, so no PRD change; rung 57 can never collide with rung 55 in practice.
2. `routes/engagements.py:157`: a `counter_round > MAX_COUNTER_ROUNDS` check on `POST /agreements/{id}/send` is unreachable — `g23_work_state(engagement, ("NOT_STARTED",))` at line 155 rejects first for any engagement that could have accumulated counters. Left undocumented rather than describing an unobservable branch.
3. `MILESTONE_SATURATION_WINDOW_DAYS`, `MILESTONE_EARLY_HOLD_HOURS`, `MAX_REVIEW_ROUNDS` are defined but unused (see Gap B). The behaviours they name are implemented with literals that happen to agree, so there is no contract divergence today — but a future edit to `config.py` would silently not take effect.
4. `calc.satisfaction_pool` applies a final `_seq`-descending tie-break when selecting the sample of 5. §3.9 describes the sort keys ahead of it but not this last tie-break. I did **not** add it: it is only reachable when two surveys share every prior key including `created_at`, and describing it would require either a new clause of doubtful observability or a claim I could not confirm holds on every call path.

## Not reached / honest gaps

- Nothing in the assignment was left undone: all 57 rungs were walked against `guards.py` and the six route modules, and all 90 `config.py` names were classified.
- Route modules were read via targeted reads around every grepped `gNN` callsite rather than end to end (per the efficiency instruction). For the four largest handlers in `engagements.py` (submit, score, handoff, valuation) I read the full function bodies. A guard invoked through a helper in `domain.py` rather than directly from a route would not have appeared in my callsite grep; I checked `domain.py` for `G.` references and found none, so I believe the map is complete, but that is an inference rather than a line-by-line read of all six route files.
- I did not read `test_suite/`, `test_helpers/`, `SCAFFOLD*.yaml`, `worklog.md`, `PRD.md`, `PRD_FINALIZED.md`, or any sibling task directory.

---

## Pipeline complete — 2026-09-01T03:00:00.000Z

All 9 steps done. Final artifact inventory:

```
SCAFFOLD.yaml                      2614 lines   (lint-clean, FINAL)
SCAFFOLD_DIFFICULTY_DESIGN.yaml    5846 lines   (9 rules / 35 instances)
SCAFFOLD_CORNER_DESIGN.yaml        6041 lines   (7 sections / 235 instances)
workspace/INSTRUCTION.md
workspace/PRD.md                    482 lines
workspace/PRD_FINALIZED.md          482 lines   (2 edits over PRD.md)
workspace/PRD_COMPLETED.md          482 lines   (62 edits over PRD_FINALIZED.md: 57 + 5)
workspace/implementation/            18 files / ~4270 lines  (Python + Flask, in-memory)
test_helpers/                         9 files / ~2667 lines
test_suite/                          16 files / 344 tests
worklog.md                          this file
```

Final test result: **344/344 passing in all 8 parallel rounds** (`--isolation per-test-server`), verified directly from `results.1..8.json`. Design coverage: 265 of 270 design instances, 0 tags pointing at non-existent instances, 5 documented PRD-first skips. Complexity: `beyond_expert`.
