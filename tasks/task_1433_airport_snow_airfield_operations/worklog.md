# Worklog — task_1433_airport_snow_airfield_operations

## Step 1: Create Task Directory — 2026-08-13T06:38:00.000Z

Pre-assigned by the pipeline invoker: `tasks/task_1433_airport_snow_airfield_operations/` with `workspace/` subdirectory already created. No index scan performed; no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-13T07:41:00.000Z

All three scaffold artifacts are generated and lint-clean. Summary:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1433_airport_snow_airfield_operations/SCAFFOLD.yaml` — §1.0–§1.7 only (response envelope, 9 entities, 10 state machines, 2 OCC concurrency rules, 6 calculations, 20 ordered validations, 35 endpoints, 32 error codes, 5 roles). No `scaffold_difficulty_design`/`scaffold_corner_design` keys inside.
- `/home/ubuntu/github/CodingPRD/tasks/task_1433_airport_snow_airfield_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` with all 9 rule_ids × 2 instances = 18 instances, each with falsifiable `distinguishing_aspect` and fully structured `setup_api_calls`/`trigger` chains.
- `/home/ubuntu/github/CodingPRD/tasks/task_1433_airport_snow_airfield_operations/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` with 75 instances (60 active + 15 `excluded_because` stubs) across all nine taxonomy sections.

## Design highlights

- **Complexity profile**: posture-driven gating (primary) + temporal windowing (secondary); layers: cascading side effects, rate thresholds, derived-field reconciliation, optimistic concurrency; flat topology; segregation-of-duties role model (chemical AUTHORIZE vs DISPENSE by distinct `X-User-ID`s).
- **Nine difficulty rules pinned**, e.g.: dual-variant cost accrual (provisional 497000 vs final 486000 cents on identical records, SnowEvent domain) vs raw-vs-capped chemical quantity (environmental domain); combinatorial modes (a) temperature-branched rate formula and (b) pinned per-line-then-sum rounding (1002 vs 1001 trap); cyclic AirfieldSurface reopen loop + SnowEvent parallel status×closure dimensions; depth-3 cascades (report supersede → NOTAM reissue → count recompute; dispense → 90% threshold → CONSTRAINED → auto-reject); priority conflicts state-vs-fiscal and safety-vs-temporal; inclusive boundaries at mu == 0.36 and raw == available; half-open shift adjacency vs closed-interval NOTAM touch-conflict; quota and NOTAM-count conservation invariants.
- **OCC** on `AirfieldSurface.version` guards both supersede-style creates (`POST /condition-reports`, `POST /friction-assessments`); logical-clock test-driving endpoint `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default.

## Verification

- `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (35 endpoints, 9 entities, 18 + 60 active instances, 501 calls scanned.)
- Two YAML syntax fixes were needed along the way (PyYAML rejects unquoted trailing-`?` optional markers and `Entity[]` list outputs inside flow mappings) — both fixed by quoting, content unchanged.
- Additional audit script confirmed: no instance-name dupes across files, all `excluded_because` refs resolve, every error code is referenced by a validation/transition and has at least one test, all endpoint roles exist in RBAC, no forbidden concurrency vocabulary, and every enum value is produced by a transition or initialization.

## Step 3: Copy Shared Files — 2026-08-13T07:42:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1433_airport_snow_airfield_operations/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T07:50:00.000Z

All checks pass. The PRD is complete.

## Report

**Generated PRD:** `/home/ubuntu/github/CodingPRD/tasks/task_1433_airport_snow_airfield_operations/workspace/PRD.md`

**Approach:** Read the doc-generator skill specification and the scaffold YAML, then produced a PRD with the standard five-section structure. The document uses a domain-derived §2 layout (RBAC, response envelope verbatim, pagination, common resource properties, logical clock, OCC, existence/hierarchy, precision/rounding, validation priority) and an 11-subsection §3 organized around entity lifecycles and cross-cutting workflows (event lifecycle, closure coordination, surface posture, condition reports, friction assessments, NOTAMs, products, applications, equipment/shifts, cost accrual, dispatch order).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs + path params + common fields: 69 required, 69 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 20 checked, 20 expressed in prose (§2.9 ordered list + workflow narratives), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (expected_surface_version + ERR_STALE_VERSION + HTTP 412 named in §2.6, §3.4, §3.5), 0 missing
- state_machines[].transitions: 22 checked, 22 fully expressed with preconditions and side-effects, 0 missing
- calculations[]: 6 checked (braking_action_from_mu, chemical_application_quantity, event_cost_accrual, condition_code_derivation, dispatch_order, seasonal_chemical_counters), 6 fully expressed in precise prose with all constants embedded, 0 missing
- validations[] conditions: 20 checked, 20 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narratives, 0 missing
- entities[].fields[] structured content: defaults, computed sources, and constraints reconstructible from prose, 0 missing
- sibling-branch symmetry: surface CLOSE from OPEN vs RESTRICTED, Notam RESCIND from ISSUED vs REISSUE_REQUIRED, and parallel cascade links all rendered with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 538
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Key scattering decisions:**
- The `worked_hours` parameter appears in §3.9 (shift completion) and §3.10 (cost accrual overtime formula).
- The `event_id` foreign key is implied through narrative ("payload containing the `event_id`", "the referenced `SnowEvent`") rather than declared as FK.
- Numeric constants embedded in business context (e.g., "three `EquipmentUnit` rows in `READY`", "at least 90% of `seasonal_limit_lbs`", "strictly below `15` degrees").
- Validation priority ordering lives in §2.9 as a single ordered list; trigger conditions live near the workflows that raise them in §3.
- The closure cascade (PROPOSED → NONE with `airline_acknowledged` reset; RATIFIED → LIFTED) is described in §3.1 alongside stand-down rather than in §3.2.

## Step 5: Generate Unit Tests — 2026-08-13T08:30:00.000Z

Complete. All generation and audit steps are done.

## What was generated

**`test_helpers/`** (9 files, all imports verified):
- `types.py` — status enums (SnowEvent, closure, surface, report, assessment, NOTAM, product, application, readiness, shift) + 9 entity TypedDicts; all entities carry `id`/`created_at`/`updated_at`/`version` per PRD §2.4
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (31 methods incl. `/_clock/set_current_utc`)
- `api_errors.py` — `ApiErrorId` (32 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` (nullable fields handled: `activated_at`, `authorized_quantity_lbs`, `superseded_by_id`, `current_condition_code`, `equipment_unit_id`, `worked_hours`) + `assert_product_quota_invariant`
- `factories.py`, `constants.py` (braking thresholds, temp factors, OT rule, 90% CONSTRAINED trigger, readiness floor, logical-clock default)
- `test_users.py` — 5 opaque-role shared header constants + per-instance `make_*_headers` builders (used to pin distinct MaintenanceLead X-User-IDs for segregation-of-duties)
- `fixtures.py` — composite setup: `create_ready_equipment`, `setup_activated_event`, `setup_event_with_surface`, OCC-threading `file_condition_report`/`record_friction_assessment` (version re-read before each guarded write), `setup_restricted_surface_with_friction`, `setup_issued_notam`, `setup_proposed_application`, authorize/dispense/void with pinned user ids, `schedule_shift`, `get_cost_summary`

**`test_suite/`** — `conftest.py` + 7 numbered files, **96 tests**, all collecting cleanly under pytest:
- `test_01` envelope/defaults/404s/pagination/clock (17)
- `test_02` event lifecycle + closure ratification (11)
- `test_03` surfaces, condition codes, friction boundaries, dispatch order (12)
- `test_04` NOTAM gates, closed-interval overlap, supersede cascade, count conservation (12)
- `test_05` chemical applications: variants, caps, budget, cascades, SoD (19)
- `test_06` shifts/equipment/dual-variant cost accrual incl. pinned per-line rounding (11)
- `test_07` authn/authz, validation ordering, temporal checks, OCC (14)

## Audit results (all programmatically verified)
- **Coverage**: all 18 `scaffold_difficulty_design` instances have exactly ≥2 tests (36 total); all 60 non-stub `scaffold_corner_design` instances have exactly ≥1 test; the 15 `excluded_because:` stubs were not translated (their difficulty-instance owners carry the assertions)
- **Tag integrity**: 96 tests / 96 `Design:` lines; every tag resolves to a real instance name; each docstring ends with exactly one tag; no untagged or dual-tagged tests
- **C1 verbatim**: every quoted PRD fragment in every docstring (down to 15 chars) survives a whitespace-normalized literal grep of `PRD.md` — 0 mismatches
- **No skips/xfail**, no `scaffold` mentions in generated code
- No instances failed the PRD-first filter — every instance in both indices had verbatim PRD coverage with uniquely-derivable outcomes

## Step 6: Generate Implementation — 2026-08-13T08:12:00.000Z

Implementation is complete. Here's a summary:

## Summary

Generated a complete Python + Flask implementation of the Airport Snow & Airfield Operations API at `/home/ubuntu/github/CodingPRD/tasks/task_1433_airport_snow_airfield_operations/workspace/implementation/`.

### Files produced
- `start.sh` — executable launcher; guards `pip install` behind `python3 -c "import flask"`; `exec python3 app.py` for foreground execution
- `requirements.txt` — `flask>=2.0`
- `app.py` — Flask app entrypoint; registers blueprints; central `ApiError` handler producing the PRD §2.2 error envelope; binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory store (`Store` class); starts empty; logical clock defaults to `2026-08-01T00:00:00Z`
- `errors.py` — all error IDs from the scaffold with their HTTP statuses
- `response.py` — success/error envelope with `meta.api_request_id` (req_ + 20 alnum), `api_request_timestamp` (ISO 8601 UTC, 3 fractional digits), `response_type`, `data`, and pagination fields (`limit`/`offset`/`total_count`/`has_more`)
- `middleware.py` — `X-User-ID` / `X-User-Role` header extraction; role validation against the 5 role names
- `services/core.py` — ISO 8601 parsing, `Decimal`/`ROUND_HALF_UP` helpers, pagination parsing (`limit` 1..100 default 10; `offset` default 0)
- `services/domain.py` — serializers, condition-code derivation, braking-action thresholds, raw chemical quantity calc, shift line cost (regular + OT 1.5x with 8h cap), event cost recompute (per-line round-then-sum), product counter recompute, OCC helpers, NOTAM supersession cascades, CONSTRAINED threshold cascade
- `routes/` — one module per resource: `snow_events.py`, `airfield_surfaces.py`, `condition_reports.py`, `friction_assessments.py`, `notams.py`, `chemical_products.py`, `chemical_applications.py`, `equipment_units.py`, `operator_shifts.py`, `clock.py`

### Key behaviors verified via end-to-end smoke tests (all pass)
- Auth 401 / role 403 enforcement, per-action role on closure-actions (ACK requires AirlineCoordinator)
- SnowEvent state machine: FORECAST → ACTIVATED (gated on >= 3 READY units) → ESCALATED → ACTIVATED → STANDING_DOWN → CLOSED; STAND_DOWN blocked by non-OPEN surfaces; CLOSE blocked by ISSUED NOTAMs; closure side effects (RATIFIED→LIFTED, PROPOSED→NONE)
- Closure actions: PROPOSE / ACKNOWLEDGE / RATIFY with runway-closure gate before airline-ack gate
- Surface actions incl. 3-link cascade on CLOSE (FILED reports → SUPERSEDED → ISSUED Notams → REISSUE_REQUIRED → active_notam_count recompute)
- REOPEN friction floor (`GOOD`/`MEDIUM` required)
- Condition report: RCAM base + downgrade rule (>50 coverage AND >=0.25 depth), supersession of prior FILED, surface OCC via `expected_surface_version` (412 ERR_STALE_VERSION), `current_condition_code` updated, surface version bumped
- Friction assessment: mu thresholds with inclusive lower bounds (0.36 → MEDIUM); supersession of REPORTED
- NOTAM: DRAFT→ISSUED→REISSUE_REQUIRED→ISSUED, RESCIND from ISSUED/REISSUE_REQUIRED with surface-OPEN gate, closed-interval window overlap (touching endpoints count), `active_notam_count` tracking
- Chemical application: raw quantity calc (`area/1000 * base_rate * temp_factor`, 1dp ROUND_HALF_UP), AUTHORIZE cap (`min(raw, event_remaining, product_available)`), `capped` boundary inclusive at equality, line cost, budget gate 422, environmental pool gate 422, CONSTRAINED flip at 90% dispensed + cascade rejecting PROPOSED applications, segregation of duties on DISPENSE, VOID compensation
- Operator shift: half-open overlap per `operator_code` (touching endpoints allowed), equipment READY gate, COMPLETE with `worked_hours`, line cost rounding (per-line round-then-sum), SCHEDULED shifts feed estimated cost; COMPLETED shifts feed actual cost
- Dispatch order: RESTRICTED/CLOSED only, sort by `priority_rank ASC, created_at ASC`, empty array is OK
- Logical clock endpoint `POST /_clock/set_current_utc` (SystemAdmin only)

### Per-test-server boot
The store is a module-level `Store()` initialized empty on every fresh `python3 app.py` process; no seeding. The logical clock is reinitialized to `2026-08-01T00:00:00Z` per boot. `start.sh` is re-runnable concurrently (the pip-install guard is a cheap no-op once Flask is importable).

## Step 7: Run Tests and Iterate — 2026-08-13T09:00:00.000Z

All 8 rounds clean: 95/95 in every round. Exiting with the summary.

## Summary

**Iterations run: 2** (iteration 1: 3 deterministic failures identical across all 8 rounds — no flakiness; iteration 2: 8/8 rounds clean, 95/95 each).

**Tests deleted (1):**
- `test_suite/test_01_envelope_defaults_and_reads.py::TestPaginationAndClock::test_clock_set_endpoint_echoes_logical_time` — RESPONSE-SHAPE SILENCE (computed-field silence variant): the test asserted `data["current_utc"] == "2026-08-10T00:00:00Z"`, but neither PRD §2.5 ("An administrative test-driving capability advances the logical clock to a supplied `to_iso8601` instant") nor the §4 endpoint table specifies any response body for `POST /_clock/set_current_utc`. The `current_utc` echo field traces only to SCAFFOLD.yaml line 742 (`output: "{ current_utc: string }"`) — a scaffold-only rule. A faithful PRD-only implementer returning `{}` per §2.2 would fail it. The PRD-covered behavior (clock advance driving `observed_at`/`measured_at` future-rejection) remains covered by test_07's temporal tests.

**Fixes applied to `test_helpers/` (1):**
- `test_helpers/api_errors.py` — added missing `ApiErrorId.ERR_PRODUCT_CONSTRAINED` enum member (the error_id is verbatim in PRD §2.9 rule 7 and §3.8, so the enum gap was a plain helper bug crashing `test_authorize_on_constrained_product_rejected` with AttributeError). Deliberately NOT added to `HTTP_STATUS_CODES`: PRD §5 omits the row for this error, so no HTTP status may be enforced for it.

**Fixes applied to `test_suite/` (2, both STEP 1c partial-coverage splits):**
- `test_02_event_lifecycle_and_closure.py::test_activate_side_effect_sets_activated_at` — relaxed `data["activated_at"] == "2026-08-01T00:00:00Z"` (exact string) to instant equality (parse, compare to `datetime(2026,8,1,UTC)`). PRD §3.1+§2.5 uniquely pin the stamped *instant* ("stamped with the current logical clock time" + "startup default is exactly 2026-08-01T00:00:00Z"), but not the *string serialization* — §2.4's three-fractional-digit rule applies only to `created_at`/`updated_at`/`api_request_timestamp`. Two-reader divergence: verbatim-stamp vs uniform-millis serializer (the implementation is the latter, and is PRD-faithful).
- `test_05_chemical_applications.py::test_authorize_on_constrained_product_rejected` — dropped the explicit HTTP 409 pin (`validate_error(resp, ERR_PRODUCT_CONSTRAINED, 409)` → no status arg). The error_id is PRD-verbatim; the 409 status appears only in SCAFFOLD.yaml line 674, not in PRD §5. Kept the exact error_id assertion and both side-effect assertions (application stays PROPOSED, no partial authorization leak).

**Fixes applied to `implementation/` (0):** none — the implementation was already PRD-faithful on all three failures; every failure traced to the test artifact layer (one scaffold-only response-shape assertion, one over-pinned serialization format, one helper enum gap plus a scaffold-only status pin).

## Step 8: Finalize PRD — 2026-08-13T09:07:00.000Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1433_airport_snow_airfield_operations/workspace/PRD_FINALIZED.md`.

## Line counts

- `PRD.md`: 302 lines; `PRD_FINALIZED.md`: 303 lines; delta **+1 line (+0.33%)** — 2 in-place sentence revisions, 1 table-row insertion.

## Changes

- **§2.5 Logical Clock** — insert — pinned the previously unspecifed response of the clock endpoint: HTTP `200` with `data.current_utc` echoing the new logical clock time serialized as ISO 8601 UTC with three fractional digits — `implementation/routes/clock.py:22-26` (strftime + `microsecond // 1000` millis, via `success_object` default 200 at `implementation/response.py:36-42`). Traces to the deleted `test_clock_set_endpoint_echoes_logical_time` (scaffold-only response-shape rule, PRD-silent).
- **§3.1 Snow Event Lifecycle** — revise — `activated_at` clause now pins the string serialization: "stamped with the current logical clock time, serialized as an ISO 8601 UTC timestamp with three fractional digits" — `implementation/routes/snow_events.py:147-148`. Traces to the relaxed `test_activate_side_effect_sets_activated_at` (PRD pinned the instant but not the serialization).
- **§5 Error Code Catalogue** — insert — added row `| ERR_PRODUCT_CONSTRAINED | 409 |` between `ERR_INVALID_SHIFT_STATE` and `ERR_STALE_VERSION` — `implementation/routes/chemical_applications.py:119` (`raise ApiError(ERR_PRODUCT_CONSTRAINED, 409, ...)`). Traces to the dropped 409 pin in `test_authorize_on_constrained_product_rejected`. (The companion `test_helpers/api_errors.py` enum gap was a pure fixture bug — the error_id was already PRD-verbatim in §2.9 rule 7 and §3.8 — so it required no PRD edit.)

## Per-edit pre-edit search log

**Edit 1 (§2.5 clock response)**
- (a) Subject: response status/body of `POST /_clock/set_current_utc`.
- (b) Paths enumerated: `implementation/routes/clock.py` (sole handler, lines 14-26 — role `SystemAdmin`, `to_iso8601` required, `current_utc` echo with 3-fractional-digit format); `implementation/response.py:36-42` (`success_object` envelope, default status 200); `implementation/db.py:18` (clock init, no response involvement); `test_helpers/api_client.py:142-143` (bare client wrapper, no assertion). No other route emits `current_utc`.
- (c) Adjustment: wording scoped to this one endpoint ("it responds with…") so it makes no claim about other endpoints; "HTTP 200" matches both `success_object`'s default and §4's generic modification rule — no conflict.

**Edit 2 (§3.1 `activated_at` serialization)**
- (a) Subject: serialization format of server-stamped timestamp fields.
- (b) Paths enumerated: `snow_events.py:147-148` (`activated_at` = logical clock via strftime+millis); `services/core.py:20-22` `now_iso_ms()` feeding every `created_at`/`updated_at` (`chemical_applications.py:58,141,144,151,155,161,164`; `airfield_surfaces.py:51,148,157`; `equipment_units.py:36,76`; `snow_events.py:53,159,195,202,217`; `operator_shifts.py:92,112,146,148,155,157`; `notams.py:94,171,173,181,184`; `condition_reports.py:77`; `friction_assessments.py:60`; `chemical_products.py:46`; `services/domain.py:303,315,345,350` via `now_iso()`); `response.py:15-19` (`api_request_timestamp`); `clock.py:23-24` (`current_utc`). Critically, client-supplied timestamps are stored/echoed **verbatim**: `condition_reports.py:96` (`observed_at`), `friction_assessments.py:66` (`measured_at`), `notams.py:100-101,167-168` (`effective_from`/`effective_until`), `operator_shifts.py:99-100` (`start_utc`/`end_utc`).
- (c) Adjustment: the format clause is attached only to the `activated_at` stamping sentence rather than stated as a global "all timestamps use three fractional digits" rule — a global claim would have mis-described the six verbatim-echo paths above. All enumerated server-stamped paths (created_at/updated_at/api_request_timestamp/current_utc/activated_at) use the identical millis format, so the scoped sentence is consistent everywhere.

**Edit 3 (§5 `ERR_PRODUCT_CONSTRAINED` row)**
- (a) Subject: HTTP status carried by `ERR_PRODUCT_CONSTRAINED`.
- (b) Paths enumerated: repo-wide grep over `implementation/` — `errors.py:45` (constant definition only), `routes/chemical_applications.py:11` (import) and `:119` (the single raise site, status 409). No other route, service, or middleware raises this error; the `errors.py` factory helpers (`unauthenticated`/`unauthorized_role`/`validation`/`not_found`) never produce it.
- (c) Adjustment: none — with exactly one raise site at 409, the catalogue row matches all implementation paths. (The Step 7 test-helper decision to leave the status unenforced reflects the old PRD's silence; the alignment target here is the implementation, which returns 409.)

## Step 9: Complete PRD — 2026-08-13T09:10:00.000Z

All edits are in place. Done.

## Summary

**Source**: `PRD_FINALIZED.md` (303 lines, 41,694 chars) → `PRD_COMPLETED.md` (308 lines, 46,410 chars), +5 lines / +4,716 chars. Only `PRD_COMPLETED.md` was edited; all changes are inline insertions/revisions — no new sections.

**Counts**: 13 ambiguity-pins, 5 mismatch-revisions (18 changes total).

### Mismatch revisions (PRD described behavior impl does not exhibit)

- §3.1 — revise — mismatch — removed "proposing" from the list of activities gated on `ACTIVATED`/`ESCALATED`; impl `create_application` performs no event-state gate — `implementation/routes/chemical_applications.py:47-76`.
- §3.8 — revise — mismatch — added that proposal requires only FK existence and is not gated on event `status` (companion to the §3.1 fix) — `implementation/routes/chemical_applications.py:47-55`.
- §2.6 — revise — mismatch — `expected_surface_version` is optional (not "must carry"); when supplied, non-integer → `ERR_VALIDATION`, mismatch → `ERR_STALE_VERSION`; when omitted no check occurs; validated only at §2.9 step 6 after state preconditions — `implementation/routes/condition_reports.py:67-73`, `implementation/routes/friction_assessments.py:51-57`.
- §2.8 — revise — mismatch — `mu_value` is validated only for range `[0.00, 1.00]`; the server neither rounds it nor enforces two decimal places (PRD had said "carried exactly at two decimal places") — `implementation/routes/friction_assessments.py:31-35`.
- §3.5 — revise — mismatch — dropped "at exactly two decimal places" requirement on `mu_value` input and aligned the OCC wording to optional-token semantics — `implementation/routes/friction_assessments.py:31-57`.

### Ambiguity pins (PRD silent; pinned to impl)

- §2.4 — insert — client-supplied timestamps (`observed_at`, `measured_at`, `effective_from`, `effective_until`, `start_utc`, `end_utc`) are stored and returned verbatim — `implementation/routes/condition_reports.py:96`, `implementation/routes/notams.py:100-101`, `implementation/routes/operator_shifts.py:99-100`.
- §2.5 — insert — the logical clock set is unconditional (no monotonicity constraint; backward sets allowed) — `implementation/routes/clock.py:20-21`.
- §2.9 (rules 9/10) — insert — "latest" `REPORTED` assessment means most recently created by `created_at`, not greatest `measured_at` — `implementation/routes/airfield_surfaces.py:161-167`, `implementation/routes/notams.py:31-37`.
- §3.1 — insert — duplicate `event_code` rejected with `ERR_VALIDATION` — `implementation/routes/snow_events.py:50-52`.
- §3.3 — insert — duplicate `surface_code` → `ERR_VALIDATION`; within the state-precondition tier, surface transition validity is checked before the event-active gate; REOPEN "latest" = most recently created — `implementation/routes/airfield_surfaces.py:48-50, 122-130`.
- §3.4 — insert — `coverage_pct` must be an integer; `depth_inches` numeric — `implementation/routes/condition_reports.py:39-47`.
- §3.6 — insert — optional `source_assessment_id`/`source_report_id` must reference existing entities (assessment resolved before report → `ERR_ASSESSMENT_NOT_FOUND` / `ERR_REPORT_NOT_FOUND`); drafting not gated on event status; ISSUE also honors window overrides; on notam-actions the NOTAM state precondition is evaluated before well-formedness of supplied window overrides — `implementation/routes/notams.py:84-92, 130-149, 167-168`.
- §3.7 — insert — duplicate `product_code` → `ERR_VALIDATION`; initial counters `reserved=0`, `dispensed=0`, `available=seasonal_limit_lbs` — `implementation/routes/chemical_products.py:43-55`.
- §3.8 — insert — budget check formula pinned: current `estimated_cost_cents` plus this application's would-be `line_cost_cents` must not exceed `budget_cents` — `implementation/routes/chemical_applications.py:131-134`.
- §3.9 — insert — duplicate `unit_code` → `ERR_VALIDATION`; invalid readiness transition → `ERR_INVALID_EQUIPMENT_STATE` (409); on shift-actions the state precondition precedes `worked_hours` well-formedness; shift `line_cost_cents` = rounded labor line + separately rounded equipment line — `implementation/routes/equipment_units.py:33-35, 64-73`, `implementation/routes/operator_shifts.py:131-144`, `implementation/services/domain.py:226-237`.
- §3.10 — insert — cost-summary `data` carries exactly `estimated_cost_cents`, `actual_cost_cents`, `chemical_used_lbs` — `implementation/routes/snow_events.py:236-241`.
- §3.11 — insert — dispatch-order: path event must exist (`ERR_EVENT_NOT_FOUND`); elements are full serialized `AirfieldSurface` objects; response is non-paginated (no `limit`/`offset`, no pagination fields in `meta`) — `implementation/routes/snow_events.py:222-229`, `implementation/response.py:55-61`.
- §5 — insert — added `ERR_INVALID_EQUIPMENT_STATE` (409) row to the catalogue; noted generic `ERR_NOT_FOUND` (404) for unmatched routes, `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) — `implementation/app.py:19-35`, `implementation/routes/equipment_units.py:72`.

Key impl files reviewed exhaustively: `implementation/app.py`, `middleware.py`, `errors.py`, `response.py`, `db.py`, `services/core.py`, `services/domain.py`, and all ten route modules under `implementation/routes/`.
