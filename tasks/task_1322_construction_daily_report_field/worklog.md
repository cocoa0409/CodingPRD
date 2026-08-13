# Worklog — task_1322_construction_daily_report_field

## Step 1: Create Task Directory — 2026-08-12T22:01:50.000Z

Pre-assigned directory `tasks/task_1322_construction_daily_report_field/` with `workspace/` subdirectory verified to exist (Step 1 treated as DONE per invocation instructions; no index scan performed, no other task_* directory touched).

## Step 2: Generate Scaffold — 2026-08-12T22:44:40.000Z

All three scaffold artifacts are written and lint-clean. Summary:

### Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1322_construction_daily_report_field/SCAFFOLD.yaml` (§1.0–§1.7 only — no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1322_construction_daily_report_field/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level `scaffold_difficulty_design:`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1322_construction_daily_report_field/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level `scaffold_corner_design:`)

(`worklog.md`/`workspace/` pre-existed from the pipeline's Step 1; untouched. No sibling `task_*` directory was read at any point.)

### Counts
- **SCAFFOLD**: 16 entities · 93 endpoints · 77 error codes · 10 calculations · 14 state machines · 41 prioritized validations · 3 OCC concurrency rules (§1.2.1) · 6 roles
- **§1.8 difficulty**: 21 instances — every rule ≥2; `combinatorial_formula`, `non_linear_state_machine`, `cross_entity_state_dependency` carry 3 each
- **§1.9 corner**: 55 instances (51 active + 4 `excluded_because` stubs) across all 9 claim-guide sections
- **Lint**: `VERDICT: clean lint` (653 calls scanned, 0 violations); plus passing sweeps for forbidden race vocabulary, error triggerability, file-split, role closure

### Notable design decisions
- **Archetype**: compliance/audit + posture-driven gating; flat topology (deliberate diversity pick — 0% in examples) with `api_prefix: "/"`; segregation-of-duties role model (submitter≠approver, creator≠signer, creator≠closer) over opaque user ids; aggregate-root OCC where every child write bumps `DailyReport.version`.
- **Posture carve-out**: `content_posture` gates all child mutations except Incident creation, which is allowed until LOCKED (claims realism) and triggers the depth-3 hold cascade: incident → `has_open_incident` → `distribution_hold` → PENDING→BLOCKED distribution records (and the symmetric release on last-incident close).
- **Dual variants**: progress percent (capped-units mean 75.00 vs uncapped cost-weighted 54.55 on identical data) and lost-day classification (calendar `>=50%` boolean vs prorated fraction 0.38).
- **Combinatorial modes a/b/c all exercised**: T&M total (tiered OT/DT 1.5×/2.0× + cross-entity STOPPAGE-conditional 0.5× standby + ceiling gate), material markup tier keyed on pre-markup subtotal (evaluation-order pin; boundary 100000 → 10%, 100001 → 5%), per-entry 3-decimal round-then-sum rollup (2.468, not 2.469).
- **Two overlap semantics**: half-open adjacency-allowed for compensable delay events per work area vs closed-interval + mandatory buffer-gap for delivery windows per zone.
- **Compensating invariants**: approve/reopen exact-inverse rollup conservation, and delivery partition `accepted+rejected+pending_recount == delivered_qty`.
- **Determinism**: logical clock endpoint with pinned startup default `2026-08-01T00:00:00Z`; strict `>` OSHA deadline boundary; all `expected_*_version` inputs are `${var}` captures per §1.8 contract 3c; all formula-derived asserts pre-computed to literals (verified by executing the formulas in Python).

## Step 3: Copy Shared Files — 2026-08-12T22:44:40.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1322_construction_daily_report_field/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T23:00:00.000Z

PRD generation complete. Summary:

**Output path:** `/home/ubuntu/github/CodingPRD/tasks/task_1322_construction_daily_report_field/workspace/PRD.md`
**Line count:** 440 lines

**Section list:**
- 1. Introduction (2 paragraphs — business context + design commitments)
- 2. Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (byte-verbatim match against the fixed source block, verified by diff); 2.3 Pagination; 2.4 Resource Identity and Audit Fields; 2.5 The Logical Clock; 2.6 Content Posture: The Editable-Versus-Sealed Gate; 2.7 Optimistic Concurrency on Report and Ticket Writes; 2.8 Numbers, Rounding, and Money; 2.9 The Validation Order; 2.10 Existence Checks and the Not-Found Vocabulary; 2.11 Idempotent Capture for Field Events
- 3. Business Logic & Workflows — 3.1 Project/Areas/Zones/Budget Lines; 3.2 Daily Report Header; 3.3 Manpower and Equipment; 3.4 Weather and Delay; 3.5 Safety, Incidents, OSHA; 3.6 Media and Deliveries; 3.7 T&M Tickets; 3.8 Quantity Entries and Rollups; 3.9 Review, Distribution, Retention
- 4. Endpoint Definitions (93-row table, 4 columns only)
- 5. Error Code Catalogue (77-row table, 2 columns only)

**Zero-Silence / Hard Contract reports:**

- **Contract 1 (Field-Name Coverage): PASS** — 143 required identifiers (all `entities[].fields[].name`, all endpoint `input`/`query_params`/dict-output keys, T&M line sub-fields, common fields) verified mechanically present as backticked tokens; 0 missing.
- **Contract 2 (Rule Coverage): PASS** — all 30 validation entries expressed with priority ordering stated as an explicit 11-layer evaluation walk in §2.9 (intra-layer order stated for state→posture→OCC and segregation-first); all 3 OCC rules expressed with write operation + `expected_report_version`/`expected_ticket_version` + `ERR_STALE_VERSION`/412 and no race framing; all 14 state machines' transitions expressed with preconditions paired to their error IDs and all side effects (approve/reopen L1–L3 rollup cascades, escalate/close hold cascades L1–L4, supersede self-reference, purge reference-clearing, retention stickiness); all 10 calculations rendered as reconstruction-safe prose (round-then-sum 2.468-vs-2.469 example, pre-markup tier boundary at 100000 cents, standby 0.5 STOPPAGE branch, strictly-greater overdue boundary, half-open shift-window intersection); all `applies_to` scopes enumerated (posture-gated operations listed in full, carve-out stated); sibling branches rendered symmetrically (dual progress variants, dual lost-day variants, both close outcomes, INSPECTED/PARTIAL inspection branches, four void source states).
- **Contract 3 (§3 Path Purity): PASS** — 696 backtick tokens scanned in §3; 0 tokens starting with `/`, 0 bare HTTP-method tokens, 0 method+path combinations.
- All 77 error IDs from the scaffold's error catalog appear in §2/§3 prose (not just the §5 table); all enum/state values and all 6 role names appear verbatim; every role's `identity: opaque` is translated into explicit §2.1 prose.

## Step 5: Generate Unit Tests — 2026-08-12T23:36:24.000Z

Generation complete. Summary:

### Tests generated

**Queue A (Difficulty, §1.8): 42 tests covering all 21 instances** — every instance has exactly 2 tagged tests:
- `dual_variant_calc`: progress_percent_units_vs_cost_weighted, lost_day_calendar_vs_prorated
- `combinatorial_formula`: tm_ticket_total_tiered_standby_conditional, material_markup_tier_keyed_on_pre_markup_subtotal, quantity_rollup_per_entry_rounding_order
- `non_linear_state_machine`: daily_report_revision_cycle, tm_ticket_signature_fork_and_revision_cycle, incident_recordable_branching_fork
- `transitive_cascade`: incident_close_releases_distribution_hold, approve_rollup_cascade_to_project_percent
- `priority_pair_validation_conflict`: ticket_approve_state_beats_fiscal, incident_create_safety_beats_temporal
- `boundary_precision_check`: ot_boundary_exactly_eight_and_twelve_hours, ceiling_equality_passes_approval
- `cross_entity_state_dependency`: submit_blocked_by_uninspected_delivery, distribution_create_blocked_by_report_state, delay_finalize_blocked_on_draft_report
- `resource_temporal_overlap`: delay_compensable_overlap_half_open_adjacency, delivery_zone_window_buffer_closed_interval
- `compensating_invariant`: approve_reopen_reapproves_conserve_installed_to_date, delivery_inspection_partition_conserved

**Queue B (Corner, §1.9): 50 tests covering 50 of 51 non-stub instances.** The 4 `excluded_because:` stubs were not translated; all four cross-references resolve to real difficulty instances (verified programmatically).

**Instances skipped (1):**
- `Corner/entities/daily_report_create_computed_input_ignored` — fails unique derivability: the PRD enumerates the create payload (project_id, report_date, optional notes/shift fields/no_work_performed) but never states that client-supplied computed/system fields (`total_workers=999`, `status="APPROVED"`) are silently ignored rather than rejected as a shape violation. Two faithful PRD-only readers could ship ignore vs reject-unknown-field variants.

**Two corner instances adapted for unique derivability** (both in `test_04`): `incident_close_requires_media_and_osha` and `incident_recordable_mismatch_both_directions` — the recipes as written trigger two failures at once, and PRD §2.9's layer-7 list order (media before recordability-mismatch) does not uniquely pin which error fires first. Tests isolate each failure: media-linked-but-unnotified → `ERR_OSHA_NOTIFICATION_REQUIRED`; notified-but-no-media → `ERR_INCIDENT_MEDIA_REQUIRED`; FIRST_AID with linked media closed RECORDABLE → `ERR_INCIDENT_RECORDABLE_MISMATCH`.

### test_helpers/ (9 files)
`types.py` (TypedDicts; WeatherObservation correctly append-only — no updated_at/version), `api_client.py` (one method per §4 endpoint), `api_errors.py` (full §5 catalog registered via `set_error_http_status_map`), `assertions.py` (per-entity + delivery-partition/manpower invariants), `factories.py` (input-fields only, collision-free unique keys), `constants.py` (thresholds: OT/DT floors, tier cap 100000, markup 10%/5%, OSHA 8h/24h), `test_users.py` (all 6 opaque roles + per-user-id builders for segregation tests), `fixtures.py` (4 tiers: entry makers, auto-OCC `add_quantity_entry`, report lifecycle DRAFT→LOCKED, fully-signed-ticket chains), `__init__.py` barrel.

### test_suite/ (conftest + 11 files, 92 test functions / 97 items with parametrization)
`test_01_entities_and_envelope`, `test_02_report_lifecycle`, `test_03_safety_and_media`, `test_04_incidents_and_osha`, `test_05_weather_and_delay`, `test_06_deliveries`, `test_07_tm_tickets`, `test_08_quantity_and_progress`, `test_09_submit_and_distribution`, `test_10_crew_and_equipment`, `test_11_security_and_concurrency`.

### Self-check results
- **Stage 1**: all helpers compile; package imports cleanly.
- **Stage 2 tag audit**: every test has exactly one `Design:` line; all 92 tags resolve to real instances in the source yamls; zero uncovered (other than the documented skip); zero difficulty instances with <2 tests.
- **PRD citation audit**: every docstring contains a ≥8-word substring surviving whitespace-normalized literal match against PRD.md (0 failures).
- **No** `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in generated code; pytest collection succeeds (97 items).

## Step 6: Generate Implementation — 2026-08-12T23:36:24.000Z

Done. The implementation is complete and verified.

### Summary

**File list** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1322_construction_daily_report_field/workspace/implementation/`):
- `start.sh` — executable launcher; guards `pip install` behind a `import flask` check (no-op on per-test reboots), then `exec python3 app.py` in the foreground
- `requirements.txt` — flask
- `app.py` — Flask entry, blueprint registration, `ApiError`/HTTP/500 error handlers, binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — empty in-memory store (no seeding), insertion-sequence counter for stable sort
- `clock.py` — logical clock pinned at `2026-08-01T00:00:00Z` at boot, settable only via the clock endpoint
- `errors.py`, `envelope.py` — `meta`/`response_type`/`data` envelope with `api_request_id` (`req_…`) and 3-fractional-digit timestamps; list meta carries `limit`/`offset`/`total_count`/`has_more`
- `auth.py` — `X-User-ID`/`X-User-Role` header check (400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`) + RBAC (403 `ERR_FORBIDDEN`) for the six roles
- `validate.py` — request-shape validators (priority 4) and pagination parsing (limit 1–100 default 10, offset ≥ 0)
- `util.py` — ISO-8601 parse/format, Decimal helpers, round-half-up quantizers (2dp/3dp/0dp)
- `calc.py` — all calculation functions
- `serializers.py` — per-entity serialization with read-time derivation of computed fields
- `routes/` — `setup_resources.py` (clock, projects, work-areas, delivery-zones, work-items), `daily_reports.py`, `field_logs.py` (crew, equipment, weather, delay), `safety.py` (observations, incidents), `evidence.py` (media, deliveries), `commercial.py` (quantity entries, T&M tickets, distribution)

**Endpoints: 93 total**, matching the §4 table exactly (all creates 201, actions 200, DELETE distribution 204).

**State machines implemented (13):** Project (MOBILIZING→ACTIVE→SUSPENDED/CLOSED with all-reports-LOCKED gate), WorkArea, DeliveryZone (OPEN↔CLOSED), DailyReport (DRAFT→SUBMITTED→UNDER_REVIEW→APPROVED→LOCKED plus recall/request-revision/return-to-draft/reopen cycles), CrewEntry, EquipmentEntry, QuantityEntry (ACTIVE→VOIDED incl. supersede with `supersedes_id`), DelayEvent (RECORDED→CLASSIFIED→DISPUTED/FINAL), SafetyObservation (OPEN→MITIGATED→VERIFIED_CLOSED/ESCALATED), Incident (REPORTED→UNDER_INVESTIGATION→OSHA_NOTIFIED→CLOSED_*), MaterialDelivery (DELIVERED→PARTIAL→INSPECTED with partition invariant), TmTicket (10 transitions incl. ordered dual signatures, revise, void), MediaAttachment (ACTIVE→PURGED), DistributionRecord (PENDING↔BLOCKED→SENT→ACKNOWLEDGED).

**Calculation functions:** `calc_manpower_split` (reg/OT/DT bands with exact 8h/12h pins), `calc_lost_hours` (half-open window ∩ shift window), `calc_lost_day_classification` (calendar ≥ boundary + prorated fraction capped at 1.0), `calc_progress_percent` (capped units mean + uncapped cost-weighted), `calc_quantity_rollup` (round-3dp-at-write, sum-stored, approve/reopen derived from report status), `calc_tm_ticket_total` (per-line integer-cent rounding, OT 1.5×/DT 2×, standby 0.5× gated on STOPPAGE weather), `calc_material_markup` (tier on pre-markup subtotal, ≤100000 → 10%), `calc_report_posture` (posture/hold/sticky CLAIMS_HOLD), `calc_osha_deadline` (+8h FATALITY/+24h LOST_TIME, strictly-greater overdue), `calc_retention_release` (max sent_at + retention_days).

**Boot verification:** `bash start.sh` launched from a fresh process on a test port, served requests correctly (200 with proper envelope), then killed. Two ad-hoc end-to-end suites (~120 assertions covering auth, validation priority ordering, OCC 412s, all state machines, calculation boundary cases, idempotency replay/conflict, hold cascades, retention arithmetic) both pass on fresh boots.

## Step 7: Run Tests and Iterate — 2026-08-13T00:03:46.000Z

Clean 8-round parallel sweep achieved: all 8 rounds report 97/97 passed, 0 failed, 0 errors.

**Iterations run:** 2 (first sweep: 86–87/97 per round, 20 unique failures in the union; second sweep after fixes: 8× 97/97).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — added `assert_instant_equal(actual, expected, msg)`, which parses both ISO 8601 UTC strings and compares the denoted instants. Rationale: PRD pins the *instant* of computed/stamped timestamps (§3.5 "falls eight hours after occurrence", §2.5 "answers with the resulting `current_utc`", §3.9 "stamping `sent_at` from the logical clock") but never pins the string serialization of these non-audit fields — the "three fractional digits" convention in §2.2/§2.4 covers only `api_request_timestamp`/`created_at`/`updated_at`. Exact-string comparison against a no-fractional-digits rendering was not uniquely derivable (a faithful implementer may normalize all server timestamps to `.000Z`), so per STEP 1c the covered instant assertion was kept and the uncovered format assertion dropped.

**Fixes applied to `test_suite/`:**
- `test_03_safety_and_media.py::test_escalate_creates_linked_incident_and_holds_distribution` — `occurred_at` string-equality → `assert_instant_equal` (format silence on the clock-stamped field).
- `test_04_incidents_and_osha.py` — 5 sites switched to `assert_instant_equal`: `test_recordable_and_non_recordable_close_branches` (LOST_TIME +24h deadline), `test_recordable_flag_by_severity` (FATALITY/LOST_TIME deadline params), `test_notification_overdue_strictly_after_deadline` (FATALITY +8h deadline), `test_clock_default_and_set` (`current_utc` echo). Instant values unchanged; only the non-PRD-pinned string format relaxed.
- `test_09_submit_and_distribution.py` — 4 instant-comparison conversions (`sent_at`, `acknowledged_at`, `retention_release_date` across the lifecycle and retention tests), plus `test_incident_on_approved_report_holds_and_blocks_send`: send of a hold-BLOCKED record relaxed to `validate_error_is_one_of([ERR_DISTRIBUTION_HOLD, ERR_DISTRIBUTION_INVALID_TRANSITION])`. This is the ERROR PRECEDENCE SILENCE pattern: §3.9 says sends during a hold are refused with `ERR_DISTRIBUTION_HOLD`, but §2.9 orders the layer-6 state precondition (record is BLOCKED, so `ERR_DISTRIBUTION_INVALID_TRANSITION`) ahead of the layer-10 distribution gates — the PRD admits both resolutions for this collision. Both errors are 409, so the status assertion is unchanged.

**Fixes applied to `implementation/`:**
- `workspace/implementation/start.sh` — dependency check changed from `python3 -c "import flask"` to `importlib.util.find_spec('flask')`, removing a full flask import (~0.3–0.5s) from every per-test reboot. This targets the sporadic "API server could not be restarted" setup errors observed under the 8× concurrent sweep (the runner's restart poll window is 15s; the errors were load-induced infrastructure flakiness, randomly distributed across tests/rounds). No application code changed; no endpoint, field, or check was added or removed — the implementation needed no behavioral fixes.

## Step 8: Finalize PRD — 2026-08-13T00:09:59.000Z

Done. `workspace/PRD_FINALIZED.md` written with exactly two edits, each tracing to a step_7_diff item.

## Line counts
- PRD.md: 440 lines; PRD_FINALIZED.md: 441 lines (+1 line, +0.23%).

## Changes
- **§2.2 (API Response Structure)** — insert — added one bullet after the `api_request_timestamp` bullet pinning that every timestamp the server emits (audit fields, clock-stamped `submitted_at`/`osha_notified_at`/`sent_at`/`acknowledged_at`/escalation-stamped `occurred_at`, computed `osha_notification_deadline`/`retention_release_date`, the clock endpoint's `current_utc`, and echoed client-supplied instants) is serialized as ISO 8601 UTC with exactly three fractional digits (e.g. `2026-08-01T00:00:00.000Z`) — `implementation/util.py:9-14` (`fmt_dt`, the sole timestamp serializer), `implementation/serializers.py:9-10,84-85,90,95,147,153,162-163,198,204-205,221,241-242,309-310`, `implementation/envelope.py:11`, `implementation/routes/setup_resources.py:59`.
- **§3.9 (Review, Distribution, and Retention)** — revise — narrowed "both creating and sending distribution records are refused with `ERR_DISTRIBUTION_HOLD`" and pinned the precedence the implementation exhibits: the record's own state precondition is evaluated before the distribution gates per §2.9, so sending a non-`PENDING` record — including one standing `BLOCKED` under a hold — fails with `ERR_DISTRIBUTION_INVALID_TRANSITION`; only a `PENDING` send reaches the hold re-check (`ERR_DISTRIBUTION_HOLD`) — `implementation/routes/commercial.py:583-593` (status check at 583-588 precedes hold check at 590-593).

## Pre-edit search log (NO-NEW-MISMATCH RULE)

**Edit A — timestamp serialization format**
- (a) Subject: string serialization of every server-emitted timestamp (the step-7 silence class: `occurred_at`, `osha_notification_deadline`, `current_utc`, `sent_at`, `acknowledged_at`, `retention_release_date`).
- (b) Enumerated/read: `util.py` (`fmt_dt` truncates to exactly three fractional digits; `parse_dt` normalizes inputs); `serializers.py` — every `fmt_dt` call site listed above, covering all resources and all instant fields; `envelope.py` (`api_request_timestamp` in all four response builders, success/list/empty/error); `routes/setup_resources.py:51-59` (clock endpoint `current_utc` via `fmt_dt`); `routes/safety.py:272` (escalate stamps `occurred_at=clock.now()`), `:434` (`osha_notified_at`), `routes/commercial.py:595,613` (`sent_at`/`acknowledged_at`), `routes/daily_reports.py:226` (`submitted_at`), `calc.py:262-267,283-296` (deadline and retention-release computation produce datetimes serialized via `fmt_dt`). The only non-`fmt_dt` outputs are calendar **dates** `report_date` and `due_date` (`serializers.py:82,182`).
- (c) Adjustment: scoped the sentence to "timestamp" (excluding the two calendar-date fields) and explicitly included echoed client-supplied instants, since `parse_dt` + `fmt_dt` normalize and re-render those too — verified true on every enumerated path, so the universal wording creates no off-site mismatch.

**Edit B — distribution send vs. hold precedence**
- (a) Subject: error precedence when sending a distribution record whose status is not `PENDING` while the report is under a distribution hold.
- (b) Enumerated/read: `routes/commercial.py` — `send_distribution` (578-598: status!=PENDING → `ERR_DISTRIBUTION_INVALID_TRANSITION` at 583-588, then hold → `ERR_DISTRIBUTION_HOLD` at 590-593), `create_distribution` (513-554: `ERR_REPORT_NOT_APPROVED` then `ERR_DISTRIBUTION_HOLD`, no record-state check possible), `acknowledge_distribution` (601-615: status-only, no hold check), `delete_distribution` (618-630: `ERR_DISTRIBUTION_ALREADY_SENT`, no hold check); `calc.py` — `distribution_hold` (313-315) and `apply_hold_cascade` (299-310); cascade callers `routes/safety.py:98` (`_create_incident`, shared by `create_incident` and `escalate_observation`) and `safety.py:500-506` (incident close). Cross-checked PRD §2.9 layer 6 (state preconditions) ahead of layer 10 (distribution gates) — already consistent, left verbatim.
- (c) Adjustment: narrowed the original blanket "creating and sending … refused with `ERR_DISTRIBUTION_HOLD`" to creating only, and phrased the send side as a precedence statement ("only a `PENDING` send reaches the hold re-check") without asserting whether that branch is reachable in practice (under the cascade invariant it is not), keeping the wording faithful to every enumerated path including acknowledge and delete, which it leaves untouched.

The `start.sh` step-7 item (importlib launcher optimization) has zero behavioral surface and produced no PRD edit. No tests were deleted and no `test_suite/`/`test_helpers/` fixes required PRD changes beyond the two items above.

## Step 9: Complete PRD — 2026-08-13T00:19:35.000Z

All changes verified: 20 lines modified in place (21 logical edits — two share the §3.9 distribution paragraph line), no lines added or removed.

**File produced:** `workspace/PRD_COMPLETED.md`

**Source vs. output:** PRD_FINALIZED.md 441 lines / 68,949 chars → PRD_COMPLETED.md 441 lines / 70,853 chars (**+1,904 chars, +0 lines** — all changes are inline in-paragraph inserts/revisions; no new sections or paragraphs).

**Counts:** 16 ambiguity-pins, 5 mismatch-revisions (21 changes total).

**Changes (one bullet each):**

- §2.3 — insert — ambiguity — sort tie-break: ties on `created_at` broken by creation order, earliest first — implementation/route_helpers.py:20-21
- §2.3 — insert — ambiguity — `has_more` = (offset + page size) < total_count; invalid `limit`/`offset`, unrecognized enum filter, or malformed date filter rejected with `ERR_INVALID_REQUEST` — implementation/envelope.py:25, validate.py:165-185
- §2.4 — insert — ambiguity — `version` starts at 1 on creation with `updated_at` = `created_at` — implementation/route_helpers.py:9-17
- §2.6 — insert — ambiguity — submitting a T&M ticket for signature added to the sealed-gate list (impl enforces `require_editable`) — implementation/routes/commercial.py:343
- §2.6 — revise — ambiguity — version-bump exception list extended to include DRAFT-ticket line replacement and distribution-record deletion (impl touches neither) — implementation/routes/commercial.py:328-330, 618-630
- §2.11 — insert — ambiguity — idempotent replay returns the original resource with the same 201 Created status — implementation/routes/safety.py:331-333, evidence.py:111-113, commercial.py:224-226
- §3.2 — insert — ambiguity — header edit is partial-update: only present fields modified; explicit null clears `general_notes`/`shift_start_actual`/`shift_end_actual`; null `no_work_performed` ignored — implementation/routes/daily_reports.py:153-160
- §3.2 — insert — ambiguity — report `report_date_from`/`report_date_to` filter bounds are inclusive — implementation/routes/daily_reports.py:121-124
- §3.4 — insert — ambiguity — dispute carries no parent-report status gate (impl allows disputing a CLASSIFIED event on any report) — implementation/routes/field_logs.py:414-429
- §3.5 — revise — mismatch — escalated incident takes its `narrative` verbatim from the observation description (no caller padding; 50-char minimum not applied), `injured_count`/`days_away` zero, and the §3.1 work-area-open check is not re-applied on escalation — implementation/routes/safety.py:269-279
- §3.5 — insert — ambiguity — incident register `recordable` filter takes the string `true`/`false` — implementation/routes/safety.py:379-383
- §3.6 — insert — ambiguity — delivery-window collision check is zone-wide across all reports — implementation/routes/evidence.py:256-257
- §3.6 — insert — ambiguity — purge clearing an observation's `media_attachment_id` is an ordinary mutation refreshing the observation's `updated_at`/`version` — implementation/routes/evidence.py:211-217
- §3.7 — insert — ambiguity — ticket line replacement is partial (only present fields replaced); explicit null `authorized_ceiling_cents` clears the ceiling — implementation/routes/commercial.py:286-327
- §3.7 — insert — ambiguity — duplicate contractor signature fails with `ERR_TICKET_INVALID_TRANSITION` — implementation/routes/commercial.py:377-382
- §3.7 — insert — ambiguity — revise leaves the stored `reject_reason` in place — implementation/routes/commercial.py:480-485
- §3.9 — revise — mismatch — request-revision `reason` is required in the body but validated-only, not stored (impl has no reason field on the report) — implementation/routes/daily_reports.py:278-287
- §3.9 — revise — mismatch — reopen `reason` likewise required but not stored — implementation/routes/daily_reports.py:320-329
- §3.9 — insert — ambiguity — distribution send does not re-check the report's own status — implementation/routes/commercial.py:578-598
- §3.9 — insert — ambiguity — automatic PENDING↔BLOCKED flips are ordinary record mutations refreshing each record's `updated_at`/`version` — implementation/calc.py:299-310
- §3.9 — revise — mismatch — locking does not finalize `retention_release_date` (lock paragraph): impl derives the release date at read time and sends remain possible on LOCKED reports — implementation/routes/daily_reports.py:332-343, commercial.py:578-598, calc.py:283-296

**Key finding behind the mismatches:** the largest divergence is retention finalization — PRD claimed lock freezes `retention_release_date`, but the implementation derives it at read time from current distribution records and permits sends on LOCKED reports, so the date keeps moving after lock. The two reason-capture claims (request-revision, reopen) and the escalate-narrative "padded by the caller" phrase were the other mismatches; everything else in the PRD (pricing, rounding, windows, OCC, validation order, segregation rules) matched the implementation exactly as pinned.
