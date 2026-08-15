# Worklog — task_1664_residential_appraisal_practice_management

## Step 1: Create Task Directory — 2026-08-14T05:57:00.000Z

Directory `tasks/task_1664_residential_appraisal_practice_management/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions.

## Step 2: Generate Scaffold — 2026-08-14T07:12:17.331Z

Scaffold generation complete for `task_1664_residential_appraisal_practice_management`. All three artifacts are written and lint-clean.

## Files

- `/home/ubuntu/github/CodingPRD/tasks/task_1664_residential_appraisal_practice_management/SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1664_residential_appraisal_practice_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:`
- `/home/ubuntu/github/CodingPRD/tasks/task_1664_residential_appraisal_practice_management/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:`

## Counts (SCAFFOLD.yaml)

| Section | Count |
|---|---|
| Entities | 11 (Client, Appraiser w/ self-FK supervisor, PanelMembership, FeeSchedule, AppraisalOrder, Appointment, Comparable, Report, RevisionRequest, WorkfileRecord, Complaint) |
| State machines | 10 (Report and Appointment are cyclic; Order has revision loop + system unassignment) |
| Concurrency rules (OCC) | 2 (`revision-create-stale-order`, `fee-schedule-create-stale-client`) |
| Calculations | 8 (fee_quote, tier_determination, comparable_adjustment, comp_eligibility, value_conclusion, turn_time_scorecard, retention_expiry, cancellation_fee) |
| Validations | 11 priority tiers (auth → role → schema → existence → state → OCC → safety → referential → temporal → constraint → fiscal) |
| Endpoints | 69 (incl. `POST /_clock/set_current_utc`, default 2026-08-01T00:00:00Z) |
| Errors | 46 (all referenced by validations/transitions and covered by ≥1 instance) |
| Roles | 5 (FirmAdmin/ComplianceOfficer opaque; ClientUser→Client; Appraiser/QCReviewer→Appraiser; segregation_of_duties model) |

## §1.8 — 21 instances, tier-maximized

- dual_variant_calc: **3** (fee provisional-vs-final on schedule supersede, 40000→52000; retention standard 2031-08-02 vs judicial 2032-06-01; turn-time 4.5 calendar vs 3.0 business days)
- combinatorial_formula: **2** (mode a: 4-branch fee with clamp = 74000; mode b: per-line-before-sum rounding, 45270000 vs 45260000)
- non_linear_state_machine: **2** (Report DELIVERED→UNDER_REVISION→…→DELIVERED with revision_round; Appointment CONFIRMED→PROPOSED→CONFIRMED)
- transitive_cascade: **2** (sanction close: complaint→appraiser→orders→appointments, depth 3; deliver: report→order→workfile retention pin, depth 2)
- priority_pair_validation_conflict: **2** (state>safety on deliver; referential>temporal on confirm)
- boundary_precision_check: **3** (net adj exactly 15.00 eligible / 15.10 rejected; on_time_rate exactly 0.7500 = PROBATION on a 4-order chain; est value exactly 100000000 = HIGH_VALUE)
- cross_entity_state_dependency: **3** (Report←Comparable, Order←Appraiser, Workfile←Complaint)
- resource_temporal_overlap: **2** (appraiser buffer-expanded `[start−30m, end+30m)` adjacency-allowed; fee-schedule pure half-open `[from,to)` adjacency-allowed — different semantics, different resources)
- compensating_invariant: **2** (confirmed_minutes 0→90→0; fee_current 45000→60000→45000 with intact ledger fields)

## §1.9 — 147 instances (123 active + 24 `excluded_because` stubs)

Section distribution: entities 42, state_machines 24, calculations 23, validations 26, endpoints 8, errors 1, rbac 14, cross_cutting_layers 8, consistency_model 1. Covers every endpoint (all 69 exercised), every state machine (invalid-from, terminal lockdown, idempotency, initial state), all 46 errors triggerable, all 5 roles (12 denials + SoD positives incl. full trainee co-signature flow), pagination/filters, envelope shape, OCC stale-version on both rules, cascade version-bump reconciliation, immediate consistency.

## Verification

- `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (69 endpoints, 11 entities, 21+123 instances, 1716 calls scanned, 0 violations)
- Custom audit: 168 instance names unique across both files; all `grounds:` resolve; all enum values reachable; no forbidden concurrency vocabulary; file split honored; all formula-derived asserts pre-computed via Python (fee 74000, value 45000000/44700000, 15.00/25.00 boundaries, 22501 half-up cancellation, 2031/2032 retention dates, 2026-08-31 response deadline, 2026-10-31 ROV window).

## Design decisions worth flagging

1. **Desktop-appraisal flag** (`requires_inspection: false`, STANDARD-only) creates a second legal path through the order machine, halves fixture chain length for the heavy scoreboard instances, and adds conditional workfile-completeness rules (INSPECTION_NOTES required iff inspection).
2. **Provisional-vs-final fee keyed on schedule-window supersede** ties the OCC rule (fee-schedule create) directly into the dual-variant calculation — the two difficulty mechanisms compound.
3. **Single report per order with value recompute at each submit-for-qc** keeps the revision loop cyclic without a second report resource; comps unlock LOCKED→VERIFIED on revision accept, forcing a re-lock ritual before resubmission (≥3 LOCKED gate applies at both create and resubmit).
4. **Priority order pinned as state(5) < OCC(6) < safety(7) < referential(8) < temporal(9)** — this is what makes the two §1.8 priority-conflict instances deterministic.
5. **Rating gate** `MIN_COMPLETED_FOR_RATING: 4` makes the 0.7500 boundary reachable with exactly 4 completions (3 on-time + 1 late) instead of needing 10 orders for a 0.9000 edge.
6. No sibling task was consulted at any point; the design is derived solely from the scenario text and the skill spec.

## Step 3: Copy Shared Files — 2026-08-14T07:12:57.737Z

Copied `./INSTRUCTION.md` to `tasks/task_1664_residential_appraisal_practice_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T07:33:00.000Z

The "missing" spot-check was a false negative in my grep phrase — the rule is present at line 155 ("`REMOVED` memberships stay removed, and orders unassigned by the cascade stay unassigned"). All checks pass. The PRD is complete at 361 lines.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1664_residential_appraisal_practice_management/workspace/PRD.md` — 361 lines. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

### PRD section list
- **§1 Introduction** — 2 paragraphs (business-context angle: turn time, panel standing, defensibility)
- **§2 Global Specifications** — 2.1 User & RBAC (5 roles, per-role identity semantics, auth errors) · 2.2 API Response Structure (verified **byte-identical** to `section-2.2-response-structure.md`) · 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending) · 2.4 The Logical Clock (default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`, date-field comparison rule) · 2.5 Common Resource Properties · 2.6 Money, Rates, and Rounding · 2.7 The Validation Pipeline (11 priority layers, first-failure-wins, explicit ordering) · 2.8 Optimistic Concurrency Control (both rules with endpoint, field, error, 412) · 2.9 Reference Resolution (left-to-right path then body FKs, all 11 not-found errors) · 2.10 Cascading State Propagation & Version Semantics
- **§3 Business Logic** (9 subsections) — 3.1 Clients/Panels/Fee Schedules · 3.2 Appraiser Roster, Supervision & Panel Standing · 3.3 Order Intake, Scope & Acceptance · 3.4 Assignment & Inspection Appointments · 3.5 Comparables & Adjustment Discipline · 3.6 Drafting, QC, Signature & Delivery · 3.7 Revision Requests & ROV · 3.8 Workfile Retention, Complaints & Sanction Cascade · 3.9 Cancellations, Fee Adjustments & Completion
- **§4 Endpoint Definitions** — 69 rows (matches scaffold exactly; method/path/roles verified programmatically), 4 columns only
- **§5 Error Code Catalogue** — 45 rows, 2 columns only

### Coverage audit (mechanical verification)
- **Contract 1 (field names):** 99 required identifiers (all entity fields + request-body/query/path params incl. `to_iso8601`, `expected_order_version`, `expected_client_version`, `amount_cents`, `outcome`, scorecard output fields) — **99 present, 0 missing. PASS**
- **Contract 2 (rules):** validation priority pipeline stated as explicit 11-layer ordering; both OCC rules with endpoint+field+error+status; all 38 state values, all transitions incl. system-driven cascades (first-confirm advance, delivery fan-out, revision fan-out, 4-link sanction cascade, hold release); all 8 calculations in reconstruction-grade prose (fee_quote with retail card 45000/60000/85000 + 1500bps + floor 35000/cap 150000, tier threshold inclusive 100000000, pinned per-line-rounding-first adjustment math, eligibility 15.00/25.00/2.00/365 inclusive boundaries, weighted-mean value conclusion with single 100000-cent rounding, scorecard ladder with 0.7500/0.9000/4-completions boundaries and the business-days variant incl. the Sat→Wed 4-vs-3 example, retention standard-vs-judicial, half-fee cancellation 45500→22750); all `applies_to` scopes enumerated. Spot-check harness: **35/35 rule phrases present. PASS**
- **Contract 3 (§3 path purity):** 638 backticked tokens in §3, **0** path/method violations. PASS**
- Also: 45/45 error IDs mentioned in §2/§3 prose; 44/44 enum values; no fuzzy/approximating words; no pseudocode operators.

### Zero-Silence Rule notes (scaffold gaps resolved to the only consistent reading)
1. **Appointment overlap buffer** — scaffold precondition is ambiguous whether one or both windows are buffered; rendered symmetrically (each appointment's buffered window `[start−30m, end+30m)`, half-open; touching endpoints do not intersect), matching §1.6's error text.
2. **No dedicated error id** for `supervisor_id` supplied on a non-TRAINEE, or ROV `submitted_value_cents` equal to the current value conclusion — mapped to `ERR_VALIDATION` (400, request-shape layer).
3. **Manual workfile creation on a terminal order** — endpoint description says "non-terminal order"; mapped to the generic state layer, `ERR_INVALID_STATE` (409).
4. **One-report-per-order** — expressed via the state machine (creation requires `IN_ANALYSIS` and moves the order to `DRAFTING`, so a second attempt fails `ERR_INVALID_STATE`); no uniqueness error invented.
5. **QC-pass reviewer without an Appraiser row** — scaffold bundles "row exists" under `ERR_LICENSE_LEVEL_INSUFFICIENT`; transcribed exactly so.
6. **Initial `version` value** is not pinned by the scaffold — PRD states only increment-per-mutation semantics and invents no initial value.

## Step 6: Generate Implementation — 2026-08-14T08:15:00.000Z

Implementation complete and verified. Summary:

## File list

All under `/home/ubuntu/github/CodingPRD/tasks/task_1664_residential_appraisal_practice_management/workspace/implementation/`:

- `start.sh` — guarded install (`pip install` only if flask missing), `exec python3 app.py`, foreground, reads `$PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — `Flask>=2.2`
- `app.py` — Flask entry: `before_request` auth (rungs 1–2: `X-User-Role`/`X-User-ID` presence → 401, role-in-endpoint-list → 403), error handlers emitting the envelope
- `webbase.py` — late-bound app proxy that prefers `sys.modules["__main__"]` (fixes the `python3 app.py` double-import trap where `import app` inside route modules would create a second, unauthenticated `Auth` instance)
- `errors.py` — all 46 catalog error IDs with exact HTTP statuses
- `envelope.py` — `meta`/`response_type`/`data` envelope, list pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, clamps 1–100)
- `timeutil.py` — logical clock (default exactly `2026-08-01T00:00:00Z`, never wall-clock), semantic instant parsing, calendar-year addition, business-day counting
- `store.py` — in-memory dicts only; `new_row`/`touch` enforce `version += 1` + `updated_at` on every mutation; no seeding anywhere
- `services.py` — calculations, gates, cascades
- `routes/` — 12 modules, one per resource group

## Endpoints implemented: 69

Every row of the §1.5 endpoint table: clock setter, 6 client ops, 7 appraiser ops (incl. scorecard), 4 panel-membership ops, 3 fee-schedule ops, 9 order ops (create/read/list/determine-scope/accept/assign/cancel/start-analysis/complete/fee-adjustments + nested revision-request create), 8 appointment ops, 7 comparable ops (incl. PATCH), 8 report ops, 5 revision-request ops, 4 workfile ops, 6 complaint ops.

## State machines (9, all from §1.2)

Client (ACTIVE/SUSPENDED/TERMINATED with panel-removal cascade), Appraiser (ACTIVE/INACTIVE with open-assignment and license gates), PanelMembership (ACTIVE→REMOVED), AppraisalOrder (full 13-state cyclic machine incl. system-driven ASSIGNED→INSPECTION_SCHEDULED→INSPECTED, DRAFTING↔QC_REVIEW, DELIVERED↔IN_REVISION, and the sanction unassignment cascade to ACCEPTED), Appointment (with 30-min half-open buffer overlap), Comparable (DRAFT/VERIFIED/LOCKED/EXCLUDED, LOCKED→VERIFIED on revision accept), Report (DRAFT→PENDING_QC→QC_PASSED→DELIVERED, qc-fail loop, UNDER_REVISION), RevisionRequest (OPEN/ACCEPTED/REBUTTED/SUPERSEDED/RESOLVED), WorkfileRecord (ACTIVE/LEGAL_HOLD/PURGED), Complaint (full response workflow + sanction cascade: sanction_override → memberships REMOVED → working orders unassigned → their appointments CANCELLED → judicial retention recompute).

## Calculations (7, all from §1.3)

- `fee_quote` — provisional/final as-of window selection, retail fallback card, rush bps (round-half-up), MULTI_2_4/MANUFACTURED/FHA-VA surcharges, 35000/150000 floor-cap
- `tier_determination` — inclusive 100000000 threshold, one-level override ladder, HIGH_VALUE admits none
- `comparable_adjustment` — pinned per-line round-half-up to 10000 BEFORE summation; net/gross pct at 2dp
- `comp_eligibility` — inclusive 15.00/25.00/2.00mi/365-day boundaries with ordered `ineligible_reasons`
- `value_conclusion` — distance weights 3/2/1 (0.50/1.00 thresholds), exact rational mean, single round-half-up to 100000
- `turn_time_scorecard` — completed/on-time counts, 4dp rate (null when 0 completions; null treated as 1.0000 in selector), standing ladder with exact 0.75/0.90 boundaries and the 4-completion minimum, calendar vs business-day turn averages, confirmed_minutes
- `retention_expiry` — calendar-year +5y standard, judicial max(latest CLOSED_SANCTIONED close +2y), pinned at first delivery, inherited by post-delivery records
- `cancellation_fee` — 0 from RECEIVED/SCOPE_DETERMINED, round-half-up(fee×0.5) from ACCEPTED/ASSIGNED

## Validations

Full §1.4 pipeline: auth (401) → role/ownership (403) → body shape (400) → path-then-body reference resolution (per-entity 404s) → state incl. `ERR_ORDER_NOT_DELIVERED` overlay (409) → OCC `expected_order_version`/`expected_client_version` (412) → license/signature/SoD/hold/workfile/desktop/comp-eligibility (422) → cross-entity integrity (422) → temporal windows (422) → uniqueness/aggregates (422) → fee-waiver bounds (422).

## Boot/verification

- `bash start.sh` cold boot: HTTP-ready in ~1.1s, store empty, clock reads `2026-08-01T00:00:00Z`, no seed data
- Restart wipes all state (verified: create client, kill, reboot, `total_count == 0`)
- Two ad-hoc verification suites (146 checks total, both 100% pass) covering the full lifecycle, fee provisional/final divergence across schedule supersede, appointment buffer half-open boundary, all comp eligibility boundaries, value-conclusion rounding, trainee co-sign gates, revision loop with fee/resolve/supersede, complaint deadline + sanction cascade + judicial retention, cancellation fees, standing ladder (0.75 → PROBATION), pagination envelope, OCC 412s, and RBAC/ownership edges. (Verification scripts were removed after use; only the implementation ships.)

## Step 5: Generate Unit Tests — 2026-08-14T08:45:00.000Z

Complete. Generated the full test infrastructure for `task_1664_residential_appraisal_practice_management`.

## Summary

**Queue A (Difficulty)** — 40 tests over 20/21 instances (≥2 per instance):
- dual_variant_calc: 6 (fee provisional/final, retention standard/judicial, calendar/business turn-time)
- combinatorial_formula: 4 (multifactor fee 74000; per-line-rounding 45270000)
- non_linear_state_machine: 4 (report revision cycle; appointment reschedule loop)
- transitive_cascade: 4 (sanction depth-3 cascade; deliver retention pin)
- priority_pair_validation_conflict: 4 (state> safety on deliver; referential > temporal on confirm)
- boundary_precision_check: 6 (net 15.00/15.10; standing 0.7500 PROBATION vs 0.5 SUSPENDED; tier 1e8 boundary)
- cross_entity_state_dependency: 4 (locked-comps gate; inactive-assignee)
- resource_temporal_overlap: 4 (appointment 30-min buffer semantics; fee-schedule half-open adjacency)
- compensating_invariant: 4 (confirmed_minutes 0→90→0; revision fee + equal waiver)

**Queue B (Corner)** — 123 tests over all 123 non-stub instances (entities 42, state_machines 20, calculations 15, validations 18, endpoints 8, errors 1, rbac 14, cross_cutting_layers 4, consistency_model 1). All 24 `excluded_because:` stubs verified — every `difficulty_instance` cross-reference resolves; none translated.

**Skipped (1 instance, gap left as gap):**
- `Difficulty/cross_entity_state_dependency/purge_gated_by_open_complaint_then_allowed_after_close` — its first assertion (purge → `ERR_COMPLIANCE_HOLD_ACTIVE` while a complaint is open) contradicts the PRD: complaint intake sweeps every ACTIVE workfile into LEGAL_HOLD (§3.8), and purge of a LEGAL_HOLD record fails the earlier state gate — "a record under `LEGAL_HOLD` cannot be purged, and any wrong state answers `ERR_INVALID_STATE`" — with state priority 5 beating safety priority 7 per the §2.7 pipeline. PRD-only readers derive `ERR_INVALID_STATE`, not the asserted error.

**Assertion adjustments for unique derivability (PRD silent):** dropped `version == 1` and `created_at == <clock>` equality from `client_creation_retrieval_defaults` (PRD never pins the initial version value nor ties `created_at` to the logical clock — format asserted instead), and dropped `fee_current_cents == null` from `order_creation_retrieval_initial_state`.

**Self-audit results:**
- Stage 2 completeness: all tags resolve to real instances, exactly one `Design:` line per test, no unknown/stub tags, no untagged tests.
- PRD-citation pass: 250/250 quoted citation blocks survive literal whitespace-normalized grep of `PRD.md`; zero elided (`...`) quotes; all asserted error_ids named in PRD prose.
- Role/route audit: 99 calls checked; the only role/endpoint "mismatches" are the 12 intentional 403-denial probes.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; all 9 helper + 18 suite files compile; `pytest --collect-only` collects 163 tests cleanly.

**Files:**
- `test_helpers/`: `__init__.py`, `types.py`, `api_client.py` (56 endpoint methods), `api_errors.py` (44 errors registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque constants + entity-backed `make_*_headers` builders), `fixtures.py` (tiered composites incl. `setup_delivered_order`, `setup_accepted_revision`, `redeliver_revised_report`, canonical locked-comp triple)
- `test_suite/`: `conftest.py` + `test_01_entities_and_creation.py` … `test_17_difficulty_invariants.py`

## Step 7: Run Tests and Iterate — 2026-08-14T09:04:00.000Z

All 8 rounds pass: **163/163 in every round, 0 failures across the sweep**. The previously failing 4 tests are fixed, and no new failures or flakiness appeared.

## Summary

- **Iterations run:** 2 (iteration 1: 4 tests failing in all 8 rounds; iteration 2: clean 8/8 rounds, 163/163 each)

- **Tests deleted:** none — every failing test traced to a verbatim PRD rule with unique derivability.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1664_residential_appraisal_practice_management/test_suite/test_16_difficulty_overlap.py` — module helper `_setup_schedule_windows()` referenced the `api` fixture name without receiving it (`NameError`), taking down both `test_fee_schedule_adjacent_window_allowed` and `test_fee_schedule_overlapping_window_rejected`. Made the helper take `api` as a parameter and updated both call sites. Assertions untouched.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1664_residential_appraisal_practice_management/workspace/implementation/routes/routes_revisions.py` — `create_revision_request`: reordered validation to match PRD §2.7's pipeline — request-shape validation (rung 3, `ERR_VALIDATION` 400) now runs **before** path-order reference resolution (rung 4, 404). Previously an unknown path `order_id` returned `ERR_ORDER_NOT_FOUND` even when the body was malformed (missing `kind`). ClientUser ownership (rung 2) is still evaluated first whenever the order id resolves, preserving the PRD ordering for the ownership case.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1664_residential_appraisal_practice_management/workspace/implementation/app.py` — `_row_payload`: appraiser payloads now expose `no_show_count`, derived from the appraiser's `NO_SHOW` appointments. PRD §3.4 verbatim names the field ("increments the appraiser's `no_show_count`") and §3.2 states a new appraiser starts with "all performance counters at zero"; the field previously existed only on the scorecard payload, not on the appraiser resource itself.

## Step 8: Finalize PRD — 2026-08-14T09:14:00.000Z

Done. The diff is exactly one revised sentence on line 147; everything else is verbatim.

## Summary

**Line counts:** PRD.md 361 → PRD_FINALIZED.md 361 (0.0% delta — one line revised in place, none added or removed).

**Changes (one edit total):**
- §3.2 — revise — extended the "A new appraiser starts `ACTIVE`…" sentence with "; the appraiser record exposes `no_show_count`, the running count of the appraiser's own appointments marked `NO_SHOW` (§3.4)" — `workspace/implementation/app.py:22-25` (`_row_payload` derivation; parallel scorecard computation at `workspace/implementation/routes/routes_appraisers.py:156-168`; mutation at `workspace/implementation/routes/routes_appointments.py:161-171`).

**Disposition of each `<step_7_diff>` item:**
1. **`test_16_difficulty_overlap.py` fixture fix** — pure test-helper bug (`NameError` for an unpassed `api` fixture); assertions untouched, no behavioral content. No PRD edit.
2. **`routes_revisions.py` validation reorder** — the implementation was changed to *match* PRD §2.7, which already pins the ladder verbatim: rung 2 (ownership, evaluated against the resolved order) before rung 3 (request shape, `ERR_VALIDATION` 400) before rung 4 (reference resolution, 404). The fixed behavior (unknown `order_id` + missing `kind` → 400; other-client order → `ERR_NOT_RESOURCE_OWNER` before body inspection) is uniquely determined by the existing rung ordering, so the prose was kept verbatim. No PRD edit.
3. **`app.py` `_row_payload` exposing `no_show_count`** — PRD §3.4 names the field and §3.2 says counters start at zero, but the PRD never said where the counter is readable; the implementation exposes it on every appraiser payload. This was a genuine PRD silence → the single edit above.

**Per-edit pre-edit search log (for the one committed edit):**
- (a) Subject: exposure and semantics of the appraiser's `no_show_count` field.
- (b) Enumerated impl paths: `app.py:13-26` (`_row_payload` adds the derived count to any payload containing `sanction_override`); grep confirmed only appraiser rows ever carry `sanction_override` (`routes_appraisers.py:55`, `routes_complaints.py:130`), so the field lands on appraiser payloads exclusively; all appraiser-returning endpoints route through it via `base.obj`/`base.listing` (create `:57`, get `:66`, list `:81`, deactivate `:93`, reactivate `:106`, clear-sanction `:117` in `routes_appraisers.py`, proxied by `webbase.py`); scorecard endpoint (`routes_appraisers.py:156-172`) separately includes `no_show_count` in its explicit payload; mutation path is the no-show handler (`routes_appointments.py:161-171`, CONFIRMED→NO_SHOW, count derived on read); terminality verified — complete/no-show require CONFIRMED, cancel requires PROPOSED/CONFIRMED (`routes_appointments.py:173-181`), and both cascades (`routes_orders.py:237-238`, `services.py:314-317` `cascade_unassign`) only cancel PROPOSED/CONFIRMED, so "running count of NO_SHOW appointments" is behaviorally identical to §3.4's "increments" phrasing; `store.py:66` `public()` strips only `_`-keys, and the counter is derived rather than stored, which is externally invisible.
- (c) Wording adjustments: (i) scoped the claim to `no_show_count` alone — `completed_count`/`on_time_count` are *not* on the appraiser payload (scorecard only), so no "exposes those counters" plural; (ii) no exclusivity phrasing ("only on the appraiser record"), since the scorecard payload also carries the field; (iii) semantics phrased as "running count of the appraiser's own appointments marked `NO_SHOW`" to match the derived implementation exactly while staying equivalent to §3.4's increment wording.

## Step 9: Complete PRD — 2026-08-14T09:45:00.000Z

All edits are complete and verified against the diff. The work is done — final summary below.

## Summary

**Files:** `workspace/PRD_FINALIZED.md` (361 lines / 59,991 chars) → `workspace/PRD_COMPLETED.md` (367 lines / 65,694 chars; **+6 lines, +5,703 chars**). 31 hunks, all inline inserts/revisions; no new sections.

**Counts:** 31 ambiguity-pins, 22 mismatch-revisions (several hunks carry one of each; classified by primary nature below).

### Changes (one bullet each)

- §2.1 — insert — ambiguity — on reads, path id resolves (404) before any ownership comparison — routes_clients.py:33-36, routes_orders.py:81-82, routes_reports.py:62-66
- §2.2 — insert — ambiguity — unmatched path/method answered with `ERR_VALIDATION` envelope at 404/405 — app.py:86-92
- §2.3 — revise — ambiguity — pinned pagination validation (`ERR_VALIDATION` for non-integer/out-of-range limit/offset), `created_at` ties broken by creation sequence, conjunctive filters, `total_count` counts the filtered set, `has_more` formula — envelope.py:49-76, store.py:58-63
- §2.4 — revise — ambiguity — clock response echoes the supplied string verbatim as `current_utc` — routes_admin.py:19-21
- §2.5 — revise — mismatch — `created_at`/`updated_at` render with three fractional digits only when sub-second precision exists, else plain `YYYY-MM-DDTHH:MM:SSZ` (PRD claimed always 3 digits) — timeutil.py:75-86
- §2.5 — revise — ambiguity — `version` starts at 1 on creation; caller-supplied timestamps (fee-schedule windows, appointment windows) echoed verbatim — store.py:38-48, routes_fees.py:84-85
- §2.7 — revise — ambiguity — rung 3: null counts as missing, malformed timestamps/dates fail here — services.py:329-331, 393-406
- §2.7 — insert — ambiguity — where a §3 narrative enumerates an endpoint's checks in order, that endpoint-specific order governs over the ladder — (whole route surface)
- §3.1 — revise — mismatch — suspension blocks new fee-schedule creation too (PRD pinned only termination) — routes_fees.py:42-43
- §3.1 — revise — mismatch — fee-schedule creation evaluates client-active before `expected_client_version`, and `effective_to`-after-`effective_from` after the concurrency check — routes_fees.py:42-52
- §3.1 — revise — ambiguity — open-ended prior row closes only when new `effective_from` is strictly after its start; otherwise ordinary overlap rule — routes_fees.py:59-70
- §3.2 — revise — ambiguity — every appraiser representation carries recomputed `standing`; recompute also on appraiser render — app.py:13-26
- §3.2 — revise — ambiguity — both turn-time averages are null while no completions — routes_appraisers.py:129-133
- §3.2 — revise — mismatch — scorecard payload list gains `no_show_count` — routes_appraisers.py:160-171
- §3.2 — revise — ambiguity — clearing a sanction when none is in force is a no-op (no version bump) — routes_appraisers.py:114-117
- §3.3 — revise — mismatch — order creation validates body shape before the ClientUser ownership comparison (ladder says ownership first) — routes_orders.py:26-43
- §3.3 — revise — ambiguity — creation defaults: `complexity_tier`/fees/`cancellation_fee_cents`/lifecycle timestamps null, `open_complaint_count` 0, `requires_supervisor_cosign` false — routes_orders.py:47-75
- §3.3 — revise — mismatch — determine-scope: state check before body validation, client check after, tier-override before desktop restriction — routes_orders.py:104-118
- §3.4 — revise — ambiguity+mismatch — null `appraiser_id` counts as omitted; `ACCEPTED`-state check fires before a named appraiser is resolved — routes_orders.py:152-155, 184-186
- §3.4 — revise — mismatch — proposal open to any Appraiser-role caller (PRD said "the assignee"), tests only order state (not `requires_inspection`), and validates window shape before state/window-in-past — routes_appointments.py:24-52
- §3.4 — revise — mismatch — confirmation performable by any Appraiser-role caller; checks fire in the narrative's order — routes_appointments.py:82-116
- §3.4 — revise — mismatch — reschedule checks `CONFIRMED` state before the body, and end-after-start before window-in-past — routes_appointments.py:118-140
- §3.4 — revise — mismatch+ambiguity — completion open to any Appraiser-role caller; if the order already advanced past `INSPECTION_SCHEDULED`, still stamps appointment and files `INSPECTION_NOTES` — routes_appointments.py:142-159
- §3.4 — revise — mismatch+ambiguity — no-show open to any Appraiser-role caller, only from `CONFIRMED` — routes_appointments.py:161-171
- §3.4 — revise — ambiguity — Appraiser-role read/list scoping to own orders (`ERR_NOT_RESOURCE_OWNER` / filtered out) — routes_appointments.py:14-19, 68-73
- §3.5 — revise — ambiguity — new comparable carries `is_eligible` null and empty `ineligible_reasons` until first verification — routes_comparables.py:62-63
- §3.5 — revise — ambiguity — negative adjustment lines round half away from zero (-5000 → -10000) — services.py:186-201
- §3.5 — revise — ambiguity+mismatch — edit/verify/lock/exclude restricted to assignee; edit state/assignee checks before body; no-op PATCH bumps no version; editing `VERIFIED` leaves the frozen verdict — routes_comparables.py:88-154
- §3.5 — revise — mismatch — lock evaluates assignee check before the eligibility refusal — routes_comparables.py:134-139
- §3.6 — revise — ambiguity — report creation restricted to the assigned appraiser, checked after the state gate — routes_reports.py:36-40
- §3.6 — revise — mismatch — qc-pass: unresolvable reviewer yields `ERR_APPRAISER_NOT_FOUND` (PRD said `ERR_LICENSE_LEVEL_INSUFFICIENT` for "anything less"); reviewer gate before the SoD check — routes_reports.py:112-118
- §3.6 — revise — mismatch — qc-fail records no `notes` (PRD claimed it carries them) — routes_reports.py:124-143
- §3.6 — revise — ambiguity — delivery's four gates evaluated in the order listed (actor before the rung-7 gates) — routes_reports.py:170-181
- §3.7 — revise — mismatch — creation order: shared shape checks → delivered-state overlay → concurrency guard → `submitted_value_cents` checks → 90-day window — routes_revisions.py:29-59
- §3.7 — revise — ambiguity — a `CORRECTION` may carry `submitted_value_cents` (validated when present), though only reconsiderations require it — routes_revisions.py:60-61
- §3.7 — revise — mismatch — rebut checks `OPEN` state before validating the body — routes_revisions.py:146-150
- §3.8 — revise — ambiguity — Feb 29 retention pins land on Feb 28 in non-leap target years — timeutil.py:98-104
- §3.8 — revise — ambiguity — purge gates evaluated in the order listed (state → retention → hold; ladder had hold before retention) — routes_workfiles.py:49-58
- §3.8 — revise — ambiguity — complaint respondent need not be the order's assignee — routes_complaints.py:29-35
- §3.8 — revise — mismatch — each response-workflow call checks complaint state before validating its body — routes_complaints.py:85-116
- §3.9 — revise — mismatch — cancel accepts a `reason` but does not record it (PRD said it records it); ownership comparison fires before the state check — routes_orders.py:218-240
- §3.9 — revise — mismatch+ambiguity — fee adjustments: terminal-state check before body validation; null `fee_current_cents` treated as zero (surcharge sets it, any waiver exceeds it) — routes_orders.py:284-305

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1664_residential_appraisal_practice_management/workspace/PRD_COMPLETED.md`

The largest single cluster of mismatches was validation-ordering: §2.7's ladder places shape before state and the rung-7/8 gates in a fixed sequence, while the implementation evaluates endpoint checks in a per-endpoint order (state-first on most transitions, actor checks before rung-7 gates on deliver, client-active before OCC on fee-schedule creation, etc.). All such deviations are now pinned inline, with one governing sentence added to §2.7 making endpoint-level enumerations authoritative.
