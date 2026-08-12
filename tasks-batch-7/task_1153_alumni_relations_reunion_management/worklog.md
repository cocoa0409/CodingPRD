# Worklog — task_1153_alumni_relations_reunion_management

## Step 1: Create Task Directory — 2026-08-11T03:23:00.000Z

Pre-assigned output folder `tasks/task_1153_alumni_relations_reunion_management` with `workspace/` subdirectory already exists (created by pipeline harness). Step 1 auto-index scan skipped per instructions; treating Step 1 as done.

Scenario: 1153. Alumni Relations & Reunion Management (university alumni association): alumni record & lost-alumni research, class-year reunion committee & volunteer coordination, event registration & ticket tiers, affinity group & regional chapter programming, engagement scoring & giving propensity, email/mail preference & suppression, milestone reunion gift campaign, memorabilia & class notes publication.

Difficulty parameter: "generate task hard than expert level!"

## Step 2: Generate Scaffold — 2026-08-11T03:45:00.000Z

All three files exist, are non-empty, parse as YAML, and `scaffold_lint.py` reports **VERDICT: clean lint**.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1153_alumni_relations_reunion_management/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design` (§1.9)

**Counts:**
- Entities: **13** (AlumniRecord, LostAlumniResearchCase, ReunionEvent, ReunionCommittee, CommitteeMembership, TicketTier, EventRegistration, AffinityGroup, ChapterProgram, CommunicationPreference, GiftCampaign, GiftPledge, MemorabiliaPublication)
- State machines: **10** (including cyclic LostAlumniResearchCase with VERIFIED→OPEN reopen loop, parallel payment×attendance dimensions on EventRegistration, review-loop on MemorabiliaPublication, posture-gated ReunionEvent)
- Calculations: **7** (engagement_score with PROVISIONAL/FINAL variants, tier thresholds, giving_propensity with pinned evaluation order, ticket_price with ESTIMATE/FINAL variants + 4-step pinned order, campaign_matching_credit with per-pledge rounding, reunion_posture, suppression_recompute)
- Validations: **10** priority-ordered (auth → authz → existence → OCC → state → referential → temporal → constraint → safety → fiscal)
- Endpoints: **86** (including `POST /alumni/_clock/set_current_utc` with mandatory default `2026-05-01T00:00:00Z`)
- Errors: **33**; Roles: **6** (Director opaque-override, Staff opaque, ReunionChair/CommitteeVolunteer/AffinityGroupLeader/Alumni entity-backed by AlumniRecord)
- Concurrency rules: **2** (OCC on AlumniRecord PUT, OCC on ReunionEvent tier-create)
- §1.8 non-stub instances: **18** (2 per rule × 9 rules, each with full structured test_recipe)
- §1.9 non-stub instances: **33** (+1 excluded_because stub), 52 unique instance names across both files
- Lint: 411 calls scanned, **clean**

**Notable design decisions (harder-than-expert calibration):**
1. **Dual-variant pairs on different domains**: ticket pricing (ESTIMATE ignores late fee vs FINAL applies it — divergence reachable purely by clock position between create and confirm) and engagement scoring (PROVISIONAL counts PLEDGED pledges at 50% vs FINAL ignores them).
2. **Combinatorial formulas in different modes**: mode (a) 4-input stacked ticket pricing with pinned evaluation order (early-bird → committee 25% → late fee → round); mode (b) per-pledge-vs-sum-then-round matching credit with amounts (155¢ @ 5000bps ×2) chosen so the two orders literally diverge (156 vs 155).
3. **Two temporal-overlap rules with different interval semantics**: ticket tiers use half-open `[start, end)` with touching allowed; chapter programs use closed intervals extended by a 60-minute post-event buffer where touching still conflicts.
4. **Depth-3 transitive cascade** (event cancel → pledge lapse → campaign totals → propensity recompute) and **depth-2** (mark-deceased → membership end → committee_count → posture flip).
5. **Posture-driven gating**: ReunionEvent.posture (GATED/OPEN/SOLD_OUT/CLOSED) derived from quorum + tier availability gates all registration operations; `capacity == 0` pinned as unlimited (never sold out), sold-out boundary at `sold_count == capacity` (not `>`).
6. **Compensating invariants on two quantities**: group budget (approve/cancel leaves committed+spent+remaining exactly conserved) and seat/revenue (confirm/refund leaves sold_count and total_revenue_cents drift-free).
7. **Lint-driven §1.5 fixes**: added single-resource GETs (`/alumni/memberships/{id}`, `/alumni/pledges/{id}`) and filtered list (`GET /alumni/programs?leader_id=`) to satisfy FK reverse-reachability; OCC payload placeholders quoted for YAML safety.

(Orchestrator note: first scaffold subagent turn was cut off before writing files; resumed via SendMessage — agent completed all three files + lint cleanly on continuation.)

## Step 3: Copy Shared Files — 2026-08-11T03:46:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `tasks/task_1153_alumni_relations_reunion_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-11T03:58:00.000Z

PRD generated and verified. `workspace/PRD.md` exists on disk (337 lines, ~54 KB).

**Sections**
1. Introduction (2 paragraphs, association pain-points angle)
2. Global Specifications — 2.1 Roles/RBAC, 2.2 API Response Structure (emitted byte-verbatim from the skill's fixed block), 2.3 Pagination, 2.4 The Logical Clock, 2.5 Common Resource Properties, 2.6 Nested Resource Retrieval, 2.7 Optimistic Concurrency Control, 2.8 Money/Scores/Rounding, 2.9 Hierarchical Consistency & Cascading Mutations, 2.10 Validation Order (priorities 1–10 as an explicit ordered list)
3. Business Logic — 8 subsections organized by business process: 3.1 Records & contact lifecycle/suppression, 3.2 Lost-alumni research, 3.3 Events & committee formation, 3.4 Tiers/pricing/registration/posture, 3.5 Groups & programs/budgets, 3.6 Campaigns & pledges/matching, 3.7 Engagement scoring & propensity, 3.8 Publications
4. Endpoint Definitions — 86 rows, 4 columns each
5. Error Code Catalogue — 33 rows, 2 columns each

**Entity coverage** — all 13 scaffold entities, all 10 state machines with every transition's preconditions and side effects (including the three cancel-scopes and the mark-deceased four-way cascade), all 7 calculations with precise prose formulas (weights, caps, pinned evaluation orders, per-pledge rounding, ESTIMATE/FINAL and PROVISIONAL/FINAL variants), all 10 validation priorities in explicit order, all 33 error IDs in prose, both OCC rules with exact field/error/status, and all 86 endpoints.

**Hard contract reports**
- Contract 1 (field names): entities+endpoint inputs+query+path params — 75 required, 75 present, 0 missing. PASS
- Contract 2 (rules): 10/10 validation priorities expressed in order; 2/2 OCC rules; 51/51 state transitions; 7/7 calculations; 33/33 error conditions matchable in prose; all endpoint side effects and applies-to scopes covered; sibling branches (3 cancel scopes, APPROVED/PUBLISHED cancel, dual calc variants) at equal density. PASS
- Contract 3 (§3 path purity): 472 backtick tokens scanned in §3; 0 paths, 0 bare HTTP methods, 0 method+path combos. PASS

**Notable writing decisions**: constants rendered in business units ($15.00 late fee, one point per $10 of giving, $10,000 capacity saturation, 10000 bps = 1.0x match); relationships implied through actions rather than declared FKs; all scaffold symbolic expressions translated to prose; the scaffold's "explicit recompute endpoint" trigger was omitted from §3.7 because no such endpoint exists in §1.5; `hard_bounce_flag` surfaced in §3.1; the preferences upsert-vs-`ERR_DUPLICATE_CHILD` tension in the scaffold mirrored faithfully without adjudication.

## Step 5: Generate Unit Tests — 2026-08-11T04:20:00.000Z

Test generation complete for `task_1153_alumni_relations_reunion_management`.

**Helper files written (`test_helpers/`)**: `types.py` (13 entity TypedDicts + 17 status/role enums), `api_client.py` (63 methods incl. test-driving clock), `api_errors.py` (33 errors + HTTP map), `assertions.py` (per-entity asserts + group budget invariant), `factories.py`, `constants.py` (PRD thresholds: lead confidence 60, reopen cap 3, 70/30 tiers, 1500 late fee, 0.75 committee factor, 100-cent pledge minimum, 60-min venue buffer, default clock 2026-05-01T00:00:00Z), `test_users.py` (opaque Staff/Director constants; mandatory `make_*_headers(user_id)` builders for entity-backed roles), `fixtures.py` (composite chains: `setup_event_with_chair`, `setup_committee_formed_event`, `setup_open_event` (tier create re-reads event version for OCC safety), `setup_active_campaign`, `setup_lost_record`/`setup_case_in_state`, `setup_group_with_leader`/`setup_proposed_program`/`setup_approved_program`, `register`/`confirm`/`register_and_confirm`), `__init__.py` barrel.

**Test counts — 65 tests, all collected by pytest** (`--collect-only` passes; `py_compile` passes on every file; zero skip/xfail markers):
- Queue A (Difficulty): 32 tests across 16 of 18 instances (≥2 each)
- Queue B (Corner): 33 tests across all 33 non-stub instances (≥1 each)
- Files: test_01 (11), test_02 (8), test_03 (10), test_04 (10), test_05 (6), test_06 (9), test_07 (6), test_08 (5), plus conftest.py

**Instances skipped (PRD-first filter)** — both `priority_pair_validation_conflict` instances:
1. `confirm_payment_state_vs_fiscal_priority` — instance asserts ERR_INVALID_STATE (409) wins when event HELD + tier sold out, but PRD §3.4 explicitly maps event-not-open to ERR_EVENT_NOT_OPEN and §2.10 never categorizes ERR_EVENT_NOT_OPEN — assertion contradicts PRD.
2. `tier_create_referential_vs_temporal_priority` — asserts reversed sales window yields ERR_REFERENTIAL_INTEGRITY; PRD §2.10 scopes referential integrity to FK linkability only — not uniquely derivable.
One corner stub (`ticket_tier_capacity_zero_unlimited_already_covered`) correctly not translated (pointer resolves to queue-A `tier_capacity_zero_is_unlimited_not_sold_out`).

**Tag audit**: 65/65 tests carry exactly one Design: tag as final docstring line; all resolve to real instances; zero unknown/duplicate/untagged. PRD-citation verbatim sweep passes literal grep. Notable derivability decisions: dropped `version == 1` on record creation (initial version not pinned); dropped "touching at buffer end is clean" half of venue-overlap instance (ambiguous in PRD prose); dropped PROVISIONAL-score numeric assertion (no endpoint exposes provisional variant).

## Step 6: Generate Implementation — 2026-08-11T04:20:00.000Z

**Files written** under `workspace/implementation/`: `start.sh` (executable, guarded pip install, `exec python3 app.py`, reads `$PORT` default 10000, binds 0.0.0.0, foreground), `requirements.txt` (Flask>=3.0,<4.0), `app.py` (app factory, error handlers, blueprint registration), `db.py` (in-memory dicts for 13 entities + suppression set + LogicalClock default exactly 2026-05-01T00:00:00Z, no wall-clock fallback, no seeding), `errors.py` (33 error factories), `response.py` (envelope per §1.0 with list meta limit/offset/total_count/has_more), `middleware.py` (role header extraction, 6 roles, require_roles), `services/common.py` (UUID/timestamp/pagination/OCC/JSON helpers; `touch()` refreshes updated_at + bumps version on every mutation incl. cascades), `services/calculations.py` (engagement 0.50/0.30/0.20 weights PROVISIONAL/FINAL, tier thresholds 70/30 inclusive, propensity 0.7+0.15+cap 0.25, ticket_price 4-step pinned pipeline late-fee FINAL-only, per-pledge round-half-up matching credit, posture derivation, suppression recompute), `services/serializers.py` (field whitelists), `services/cascades.py` (end_membership, cancel_registration, lapse_pledge, mark_alumnus_deceased, cancel_event 3 scope variants, reunite_alumnus), 13 route modules under `routes/`.

**Verification**: py_compile PASS on all 19 .py files; smoke boot PASS (401 unauthenticated, 200 empty list with pagination meta, 404 ERR_NOT_FOUND, clock set echoes current_utc); route parity vs SCAFFOLD §1.5: **86/86 (method, path) pairs match — 0 missing, 0 extra**; end-to-end functional smoke (record → event → committee → invite/accept CHAIR → form → tier w/ OCC → open → register → confirm-payment) all expected; OCC stale-version rejection observed.

## Step 7: Run Tests and Iterate — 2026-08-11T04:45:00.000Z

All 8 rounds pass 65/65.

**Iterations run:** 2 (iteration 1: 7-8 failures/round across 8 rounds; fixes applied; iteration 2: clean 8× 65/65).

**Tests deleted:** None. Every failing test traced to a PRD-verbatim rule; no PRD-silence or unique-derivability deletions were warranted.

**Fixes applied to `test_helpers/`:**
- `test_helpers/api_client.py` — `ApiClient.__init__` now sets `Connection: close` on the session. The session-scoped client's pooled keep-alive connection raced the runner's per-test SIGKILL/respawn, surfacing as `ConnectionResetError` mid-test (flaky `test_volunteer_cannot_accept_others_membership`, rounds 6-7). One TCP connection per request eliminates stale-pool reuse; no assertion changed.

**Fixes applied to `test_suite/`:**
- `test_02_events_committees_publications.py::test_membership_accept_on_locked_committee_rejected` — test bug (STEP 2): setup invited a member AFTER `setup_open_event` locked the committee, but PRD §3.3 ("all membership mutations are thereafter rejected") makes that invite itself rejectable. Rewrote setup to invite while unlocked (COMMITTEE_FORMED), then open registration to lock, then assert `ERR_COMMITTEE_LOCKED` on accept. Added `create_tier`, `set_clock` imports.
- `test_03_tiers_and_pricing.py` — added missing `create_committee` import (NameError in `test_stacked_discounts_estimate_at_creation` and `test_stacked_discounts_final_at_confirmation`); in `test_tier_window_touching_at_endpoint_allowed`, replaced the verbatim-string echo assertion (`sales_start == "2026-06-01T00:00:00Z"`) with instant-equality comparison — PRD pins the three-fractional-digit format only for server-generated timestamps, not user-supplied field echoes, so the format assertion was not uniquely derivable (STEP 1c: kept the PRD-covered "touching windows allowed" assertion, relaxed the uncovered format pin).
- `test_06_campaigns_and_pledges.py` — added missing `setup_open_event` import (NameError in `test_event_cancel_abandons_campaign_and_lapses_pledges` and `test_event_cancel_lapse_decrements_pledged_total_without_giving`).

**Fixes applied to `implementation/`:**
- `services/common.py` — `json_body()` gained an `allow_query` fallback: when no JSON body is present, read fields from the query string. The harness `GenericApiClient` sends DELETE payloads as query params, so `DELETE /alumni/suppression-list` (a verbatim PRD §4 endpoint) was unreachable via the harness convention (400 "Request body must be JSON" in `test_global_suppression_list_round_trip`).
- `routes/preferences.py` — `remove_suppression` now calls `json_body(required=["alumni_id", "channel"], allow_query=True)`. Smoke-verified: add → `GLOBAL_LIST`, remove via query params → `NONE`.

**Note on `test_research_case_reopen_returns_to_open_and_counts` (restart error, all 8 rounds, iteration 1):** infrastructure contention (all 8 rounds hit their 9th restart in lockstep; the 15s readiness poll exhausted under the synchronized boot spike). No test or implementation defect — it passed in all 8 rounds of iteration 2 once the suppression test stopped failing fast and the client transport was hardened.

Orchestrator verification: all 8 `results.{1..8}.json` files present on disk, each passed=65 total=65.

## Step 8: Finalize PRD — 2026-08-11T04:50:00.000Z

PRD_FINALIZED.md written at `workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md: 337 lines; PRD_FINALIZED.md: 339 lines (+2 lines, +0.59%).

**Changes (one bullet per edit):**
- **§2.5 Common Resource Properties** — insert — added one paragraph after the `version` bullet: client-supplied ISO 8601 datetime fields on resources (`event_date`, `sales_start`, `sales_end`, `venue_slot_start`, `venue_slot_end`) are interpreted as instants and stored/echoed in the canonical UTC three-fractional-digit format, whatever lexical form was submitted (example: `2026-06-01T00:00:00Z` → `2026-06-01T00:00:00.000Z`) — `implementation/routes/events.py:40,53`, `implementation/routes/ticket_tiers.py:52-53,76,78`, `implementation/routes/programs.py:49-50,66,68`, `implementation/services/common.py:21-25`.
- **§4 Endpoint Definitions** — revise — DELETE `/alumni/suppression-list` row description extended with "; the pair may be supplied as query parameters when no JSON body is sent" — `implementation/routes/preferences.py:123-139`, `implementation/services/common.py:64-85`.

**Step 7 items requiring no PRD change:** test_02 locked-committee rewrite (pure fixture bug; PRD §3.3 already pins lock semantics; impl committees.py:96-97,178-179 agrees); test_03/test_06 missing imports (fixture NameErrors, no behavioral content); test_helpers `Connection: close` (transport-only).

**Per-edit pre-edit search log (NO-NEW-MISMATCH RULE):**
- Edit 1 (timestamp normalization): subject = echo format of client-supplied ISO 8601 datetime fields. Enumerated via repo-wide grep of parse_iso/format_ts: events.py:40,53 (event_date); ticket_tiers.py:52-53,76,78 (sales_start/sales_end); programs.py:49-50,66,68 (venue_slot_start/end); clock.py:17-19 (input-only; current_utc server-generated); services/common.py:16-25 (logical_ts/format_ts cover all server-stamped fields). Confirmed no other resource takes a client datetime. Wording explicitly names the four client-supplied fields and scopes to "client-supplied ... on resources", asserting nothing about current_utc or server-stamped fields (invited_at, pledge_date, lost_since, resolved_at).
- Edit 2 (DELETE suppression-list query params): subject = how (alumni_id, channel) is carried on DELETE /alumni/suppression-list. Enumerated via grep of allow_query: sole call site routes/preferences.py:127; semantics services/common.py:64-85 (JSON body precedence, query only when no body, 400 ERR_INVALID_REQUEST if neither); add_suppression POST is JSON-only; DELETE exists on no other endpoint. Wording scoped to the single §4 DELETE row, "may be supplied as query parameters when no JSON body is sent".

## Step 9: Complete PRD — 2026-08-11T04:58:00.000Z

**File written:** `workspace/PRD_COMPLETED.md`

**Size:** PRD_FINALIZED.md 339 lines / 54,527 chars → PRD_COMPLETED.md 339 lines / 58,028 chars (+3,501 chars, line count unchanged — all edits in-paragraph; no new sections).

**Counts:** 20 ambiguity-pins, 4 mismatch-revisions (24 edited passages total; two edits bundled two pins each).

**Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref):**
- §2.3 Pagination — insert — ambiguity — out-of-range/non-integer limit/offset rejected with ERR_INVALID_REQUEST — services/common.py:88-104
- §2.3 Pagination — insert — ambiguity — sort ties on created_at broken by id ascending — services/common.py:109
- §2.4 Logical Clock — revise — mismatch — "advances" → "sets ... unconditional; supplied instant may be earlier, equal, or later" (no monotonicity check) — routes/clock.py:15-19, db.py:37-38
- §2.5 Common Properties — insert — ambiguity — version starts at 1 on creation — services/common.py:58
- §3.1 Record create — insert — ambiguity — duplicate primary_email on non-DECEASED record fails ERR_INVALID_REQUEST — routes/records.py:33-40
- §3.1 mark-lost — insert — ambiguity — CONFIRMED-on-open-event refusal is ERR_INVALID_STATE (HTTP 409) — routes/records.py:137-143
- §3.1 Suppression list — insert — ambiguity — add/remove return recomputed preference row, or 201/200 echo objects {alumni_id, channel, suppressed, suppression_reason} when no preference row exists; preference upsert POST always answers 201 — routes/preferences.py:103-139, 57-72
- §3.1 mark-deceased — insert — ambiguity — record must currently be ACTIVE; from LOST/DO_NOT_CONTACT fails ERR_INVALID_STATE — routes/records.py:179-180
- §3.1 Deceased cascade — revise — mismatch — committee_count decremented only for memberships that were ACTIVE (INVITED endings never touch the count) — services/cascades.py:21,29-33
- §3.2 Research case create — revise — mismatch — case creation validates only record existence (ERR_NOT_FOUND); LOST requirement enforced at log-lead and reunite, not at open — routes/research_cases.py:53-57,101-103,145-147
- §3.2 Research case create — insert — ambiguity — lead_confidence outside 1–100 fails ERR_INVALID_REQUEST — routes/research_cases.py:43-45
- §3.2 reunite — insert — ambiguity — reunite also recomputes suppression on all the alumnus's preference rows — services/cascades.py:124-130
- §3.3 Event create — insert — ambiguity — committee_quorum_required must be an integer ≥ 1 else ERR_INVALID_REQUEST — routes/events.py:41-46
- §3.3 Committee invite — insert — ambiguity — invite rejected ERR_COMMITTEE_LOCKED when locked; named alumnus must exist and not be DECEASED else ERR_REFERENTIAL_INTEGRITY — routes/committees.py:96-105
- §3.3 Membership end — insert — ambiguity — direct end records ended_reason RESIGNED (by CHAIR) vs REMOVED (by staff/director) — routes/committees.py:229
- §3.3 form-committee / mark-held / reconcile — insert — ambiguity — missing committee or zero members, clock before event_date, and outstanding PENDING_PAYMENT each fail ERR_INVALID_STATE — routes/events.py:100-104,138-139,151-153
- §3.3 Event cancel — insert — ambiguity — cancel from HELD/RECONCILED/CANCELLED fails ERR_INVALID_STATE — routes/events.py:163-164
- §3.3 Event cancel (OPEN scope) — revise — mismatch — membership-ending count decrement applies only to previously ACTIVE memberships — services/cascades.py:114-119 + 29-33
- §3.4 Tier create — insert — ambiguity — tier creation permitted regardless of event status; negative base_price_cents/capacity, pct outside 0–90, or sales_start not strictly before sales_end → ERR_INVALID_REQUEST — routes/ticket_tiers.py:35-61
- §3.4 Registration create — insert — ambiguity — no event-status check beyond the sales window; duplicate registrations (same alumnus/tier/event) permitted — routes/registrations.py:36-75
- §3.4 Refund — revise — mismatch — only an exactly-HELD event blocks refund (ERR_EVENT_ALREADY_HELD); refund remains permitted after RECONCILED — routes/registrations.py:158-159
- §3.5 Program create — insert — ambiguity — venue_slot_start must be ≤ venue_slot_end and budget_allocated_cents ≥ 0, else ERR_INVALID_REQUEST — routes/programs.py:51-55
- §3.5 Program complete — revise — mismatch — missing/negative actual_spend_cents → ERR_INVALID_REQUEST; only exceeding budget_allocated_cents → ERR_SPEND_OVERRUN — routes/programs.py:197-202
- §3.6 Campaign create/activate — insert — ambiguity — negative matching_multiplier_bps → ERR_INVALID_REQUEST at create; goal_cents ≤ 0 at activation → ERR_INVALID_REQUEST — routes/campaigns.py:44-46,91-92
- §3.6 Pledge fulfill — insert — ambiguity — DECEASED pledgor fails ERR_REFERENTIAL_INTEGRITY — routes/pledges.py:120-121
- §3.7 Giving propensity — insert — ambiguity — 365-day recency window is inclusive at both ends — services/calculations.py:88-94
- §3.8 Publication submit-review — insert — ambiguity — empty class_notes_body fails ERR_INVALID_REQUEST — routes/publications.py:76-77
- §3.8 Publication publish — insert — ambiguity — engagement recompute covers every distinct alumnus holding any registration on the event, regardless of payment_status — routes/publications.py:130-135
