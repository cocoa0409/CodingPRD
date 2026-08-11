# Worklog — task_1112_custom_application_spray_service

## Step 1: Create task directory — 2026-08-10T17:31:00.000Z

Pre-assigned output folder `tasks/task_1112_custom_application_spray_service` with `workspace/` subdirectory already existed per the run prompt; Step 1 auto-index scan skipped as instructed. Verified directory is present and empty except `workspace/`.

## Step 2: Generate scaffold — 2026-08-10T18:34:00.000Z

Scaffold generation complete and lint-clean. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_1112_custom_application_spray_service/`:

**Design summary (compliance_audit × temporal_windowing, flat topology, cyclic machines, segregation_of_duties role model):**
- **14 entities**: Customer, Field, Product, CompatibilityRule (self-referential product-pair junction), Prescription, Applicator, Equipment, CalibrationRecord, WeatherObservation, WorkOrder, ApplicationRecord, RinsateRecord, DriftComplaint, Invoice
- **55 endpoints**, **32 error codes**, **8 calculations**, **7 state machines** (WorkOrder, ApplicationRecord, Applicator, and Equipment all have live cycles), **6 roles** (Grower/Applicator entity-backed; Agronomist/Dispatcher/ComplianceOfficer/CoopAdmin opaque), 2 OCC concurrency rules (prescription-approve on `Field.version`, workorder-reschedule on `WorkOrder.version`), logical-clock endpoint with the mandatory `2026-05-01T00:00:00Z` default

**Key mechanics per the scenario:** prescription-gated work orders with per-acre + per-product-markup billing (provisional-vs-final dual variant, pinned per-line-then-sum rounding), tank-mix compatibility with CONDITIONAL adjuvant gating, nested min/max weather envelope with 60-minute observation freshness, REI lockout (`rei_until = completed_at + max(rei_hours)`, half-open), rinsate accounting invariant (ceil loads × tank × 0.02, balance must reach 0 to close), drift-complaint investigation with weighted rolling/lifetime penalty scores and license revocation at rolling ≥ 10, calibration PASS/FAIL at error_pct ≤ 5.0 with 180-day validity, and two OCC create-with-supersede/amend races.

**§1.8**: 18 instances (9 rules × 2), all with structured `setup_api_calls`; every formula-derived assert is a pre-computed literal (e.g., provisional 1065000 vs final 1120000; rounding-trap 15001 vs 15000; rinsate 24.0/16.0; rolling 8 vs lifetime 4; revocation boundary exactly 10).
**§1.9**: 59 instances across all nine claim-extraction sections (incl. `excluded_because` stubs citing real §1.8 instances), covering every error code, RBAC denials, segregation-of-duties, both OCC paths, pagination/envelope, FK reverse-reachability, and the close-gate progression.

**Final lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(52→55 endpoints after adding GET-by-id for CompatibilityRule/CalibrationRecord/RinsateRecord to satisfy check (f); 18 §1.8 + 59 §1.9 instances, 983 calls scanned.) Additional audits passed: no forbidden concurrency vocabulary, unique instance names across both design files, all `grounds` resolve, every error code is exercised by at least one instance.

## Step 3: Copy shared files — 2026-08-10T18:37:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1112_custom_application_spray_service/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T18:48:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1112_custom_application_spray_service/workspace/PRD.md`. The withheld design files were not opened or referenced.

**Document design (domain-derived, not template-copied):**
- §1: 2-paragraph introduction from the regulatory/operational angle.
- §2: 10 subsections — RBAC, verbatim response structure, pagination, resource identity, logical time (the `2026-05-01T00:00:00Z` default clock), units/money/rounding, OCC, cascading reconciliation, validation precedence (all 10 scaffold priority tiers in explicit order), and the grower credit ledger.
- §3: 9 subsections organized by operational lifecycle (registry → prescriptions → people/machines → booking gauntlet → field execution → certification → rinsate/close-out → drift complaints/disciplinary cascade → invoicing/settlement), with constants embedded in business context (e.g., the 0.02 rinse fraction rendered as "two hundredths of a tank per load", the 30-minute travel buffer, the 60-minute observation freshness, the 180-day calibration horizon).
- §4: 55-row endpoint table, 4 columns only. §5: 32-row error table, 2 columns only.

**Hard contract reports:**

```
Field coverage check:
- entities[].fields: 76 required, 76 present, 0 missing
- endpoints[].request_body (incl. clock output current_utc): 64 required, 64 present, 0 missing
- endpoints[].query_params: 0 declared in scaffold (filters reuse field names, all present); limit/offset present
- endpoints[].path_params: 1 required ({id}), present
- common/line keys id, created_at, updated_at, version, product_id, rate_per_acre, actual_rate_per_acre: all present
Status: PASS
```

```
Rule coverage check:
- validations[] priority ordering: 10 tiers checked, 10 expressed in §2.9 ordered prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (prescription approve w/ expected_field_version; reschedule w/ expected_work_order_version; both ERR_STALE_VERSION/412, no race framing), 0 missing
- state_machines[].transitions: 28 checked (7 machines), 28 fully expressed with preconditions + error ids + side effects incl. all 3 complaint-substantiation cascade hops and the SCHEDULED→DRAFT revert field-clearing set, 0 missing
- calculations[]: 8 checked (invoice_amount dual-variant with pinned per-line rounding order, mix_weather_envelope with tie-break + inclusive boundaries, rinsate_generation ceil-loads formula, calibration_verdict 5.0-inclusive PASS, applicator_compliance_score 365/90-day doubler and exactly-10-revokes boundary, rei_window half-open lockout, outstanding_balance, schedule_overlap_rules with field adjacency allowed vs padded applicator back-to-back conflict), 8 fully expressed in pseudocode-free prose, 0 missing
- validations[] conditions: all error ids matchable to trigger prose in §2/§3 (32/32 present), 0 missing
- endpoints[].side_effects / applies_to: 55 checked, expressed, 0 missing
- entities[].fields[] structured content (defaults, nullability, computed semantics): all reconstructible from prose
- sibling-branch symmetry: schedule gate chain, PASS/FAIL, CONDITIONAL/INCOMPATIBLE, FIELD_DISPOSAL/CONTAINMENT_DISPOSAL, DRAFT/ISSUED void, SUSPEND/REVOKE hops all rendered with equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 462
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional precision checks: §2.2 matches the fixed reference block byte-for-byte (only structural difference is the `---` separator after the block, matching the reference example output); all 23 state values, 12 non-state enum values, and 6 role names appear with exact spelling; no pseudocode operators or fuzzy/approximating words anywhere in the document; no paragraph starts with "The system".

## Step 5: Generate unit tests — 2026-08-10T19:40:00.000Z

Test generation is complete. Summary of what was produced and the key adjudication decisions:

## Generated files

**`test_helpers/` (9 files)** — `/home/ubuntu/github/CodingPRD/tasks/task_1112_custom_application_spray_service/test_helpers/`:
- `types.py` — 14 entity TypedDicts + 12 enums; the four evidence records (CompatibilityRule, CalibrationRecord, WeatherObservation, RinsateRecord) correctly omit `updated_at`/`version` per PRD §2.4.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (49 methods), `api_client` singleton.
- `api_errors.py` — all 33 error IDs mapped to PRD §5 HTTP statuses, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions; append-only entities assert `updated_at`/`version` are *absent*.
- `factories.py`, `constants.py` (pre-computed expected amounts: 1065000/1120000/945000/15001, rinsate 24.0/16.0, clock anchors), `test_users.py` (opaque-role shared constants + mandatory `make_grower_headers(customer_id)` / `make_applicator_headers(applicator_id)` for the two entity-backed roles).
- `fixtures.py` — composite tiers: `base_environment` / `scheduled_environment` / `in_progress_environment` / `completed_environment` / `certified_environment`, plus granular creators, `approve_prescription` (refreshes Field version for OCC), `get_record_for_work_order`/`get_invoice_for_work_order` (via the PRD-named `work_order_id` filters), and complaint chains.

**`test_suite/` (10 files, 85 tests)** — `conftest.py` + `test_01`…`test_09` grouped by concern (registry/envelope, prescriptions, scheduling gates, overlaps/OCC, execution/weather, completion/records/rinsate, close/invoicing, complaints/discipline, equipment/calibration/RBAC).

## Coverage audit (all machine-verified)
- All 18 difficulty instances have ≥2 tests (36 tests); all 48 non-stub corner instances have ≥1 (49 tests). Every docstring ends with exactly one verbatim `Design: Difficulty/...` or `Design: Corner/...` tag resolving to a real instance; no untagged/dual/bad tags. The 11 `excluded_because:` stubs are untranslated; all their difficulty-instance cross-references resolve.
- 133 quoted PRD citation spans grep-verified verbatim against `PRD.md` (0 failures after fixing bold-label prefixes and ellipses). No `skip`/`skipif`/`xfail`, no scaffold references. `pytest --collect-only` collects 85 tests cleanly.

## Notable PRD-first adjudications
- **Revocation cascade restructured for unique derivability**: PRD §3.8 conditions `REVOKED` on a *SUSPENDED* applicator, making the recipe's reinstate-then-revoke (ACTIVE at rolling ≥10) ambiguous. Both `complaint_substantiation_revocation_cascade` and `revocation_threshold_exactly_10` are instead driven so the applicator is SUSPENDED when the score crosses 10 (second substantiation without reinstatement; complaint 2 filed within its 30-day window but substantiated 104 logical days later to suppress the 90-day doubler → rolling exactly 10).
- **`close_gate_progression`**: PRD §2.9 does not pin intra-category order between `ERR_RINSATE_BALANCE_OPEN` and `ERR_INVOICE_UNSETTLED`, so the recipe's ambiguous mid-step was split into two tests where each gate fails in isolation.
- **Sub-assertions dropped where PRD is silent**: `version == 1` at creation (initial value never pinned by PRD), `calibration-records?equipment_id=` filter (PRD names no filter params for that endpoint — test uses unfiltered list + GET-by-id instead), `work-orders?field_id=` filter (only `application-records`/`invoices` `work_order_id` filters are PRD-named; the work-order leg uses the unfiltered list).
- **Cancel-retains-assignment** (needed by `state_beats_safety_on_cancelled_start`) was kept as derivable: PRD §3.4's cancel specifies only status+version, in explicit contrast to §2.8's enumerated field-clearing cascade.

## Step 6: Generate implementation — 2026-08-10T19:40:00.000Z

Implementation complete. The Custom Spray Service API is fully built and verified in `/home/ubuntu/github/CodingPRD/tasks/task_1112_custom_application_spray_service/workspace/implementation/`.

**Files produced:**
- `start.sh` — executable foreground launcher; guarded `pip install` (no-op once Flask is importable, safe for concurrent per-test reboots), `exec python3 app.py`
- `app.py` — Flask wiring: `/api/*` auth gate (401 before routing), global request lock, error handlers (ApiError → envelope, 404/405 → `ERR_NOT_FOUND` envelope), binds `0.0.0.0:$PORT` (default 10000)
- `store.py` — in-memory store, empty at boot, logical clock starting at exactly `2026-05-01T00:00:00Z`
- `util.py` — response envelope (`meta.api_request_id`/`api_request_timestamp` + `response_type` + `data`, pagination fields `limit/offset/total_count/has_more`), error envelope (`error_id`/`message`), ISO-8601-with-millis timestamps, Decimal half-up helpers, field validators, `X-User-ID`/`X-User-Role` auth with the six exact role names
- `domain.py` — serializers (mutable entities carry `updated_at`/`version`; the four evidence records carry only `id`/`created_at`), invoice amount (per-line half-up rounding then summed, fee rounded independently), weather envelope (min wind / max-min temp band / inversion, 60-min freshness, tie-break by `created_at`), overlap rules (field half-open `[start,end)` adjacency allowed; applicator padded 30-min travel buffer where back-to-back conflicts), cascade helpers
- `routes_registry.py`, `routes_rx.py`, `routes_people.py`, `routes_work.py`, `routes_records.py`, `routes_compliance.py` — all 55 endpoints from the scaffold endpoint table

**Key behaviors verified live (121 checks across three test rounds, all passing):** full happy path (customer → field → products → prescription → approve → calibrate → schedule → start → weather hold → resume → complete → certify → issue → pay → dispose rinsate → close); exact invoice math (224000/233200 cents) and half-up rounding on fractional inputs; calibration boundary (error 5.0 passes); REI half-open boundary; OCC 412s on approve and reschedule; supersede cascade bumping `Field.version`; FAIL-calibration and substantiation cascades reverting SCHEDULED orders to DRAFT; ISSUED-invoice void crediting `outstanding_cents`; rolling score with 90-day doubler (2+2→8, then MAJOR→18→REVOKED, including ACTIVE→REVOKED directly when rolling ≥ 10 per the revocation threshold rule); `ERR_INVESTIGATION_PENDING`, `ERR_COMPLAINT_HOLD`, `ERR_COMPLAINT_WINDOW_CLOSED`, credit-limit gates, and validation precedence (auth → role → ownership → shape → existence → state → safety → temporal → domain → fiscal).

**One judgment call worth noting:** PRD §3.8 literally conditions revocation on being SUSPENDED, but the calculation rule states `revocation: rolling >= 10`; I implemented threshold semantics (rolling ≥ 10 revokes from ACTIVE or SUSPENDED) since the boundary comment "exactly 10 revokes" only makes sense that way. Also, server state confirmed empty on fresh boot — no seeding anywhere; every entity is built via the declared API surface.

**Orchestrator note (post-Step-6 verification):** all 55 SCAFFOLD.yaml (method, path) endpoint pairs match the Flask blueprint route registrations exactly (0 missing, 0 extra); all Python files in test_helpers/, test_suite/, and workspace/implementation/ parse cleanly (only 4 unused-import lint warnings).

## Step 7: Run tests and iterate — 2026-08-10T19:42:00.000Z

**Summary**

- **Iterations run**: 2 (iteration 1: 9 deterministic failures × 8 rounds; iteration 2: clean).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**:
  - `test_helpers/constants.py` — `CALIBRATION_VALID_UNTIL_DEFAULT` and `REI_UNTIL_STANDARD` changed from `...T00:00:00Z` / `...T10:30:00Z` to the three-fractional-digit wire form (`...T00:00:00.000Z`, `...T10:30:00.000Z`). PRD states verbatim: "Timestamps throughout the API are ISO 8601 UTC strings with three fractional digits" (PRD §2, line 84), so the expected-value constants must be expressed in the mandated wire format. Both constants are used only in response assertions, never as request inputs.

- **Fixes applied to `test_suite/`**:
  - `test_04_scheduling_overlaps.py` (`test_workorder_reschedule_stale_version`, lines 183 & 196) — expected `scheduled_start` literal updated to `2026-05-11T08:00:00.000Z` per the same PRD timestamp-format rule.
  - `test_05_execution_weather.py` (`test_work_order_weather_hold_cycle`, line 210) — expected `started_at` literal updated to `2026-05-10T08:00:00.000Z`.
  - `test_06_completion_records.py` (`test_complete_creates_application_record_snapshot`, lines 192–193; `test_rei_until_takes_max_across_completions`, line 322) — expected `started_at` / `completed_at` / `rei_until` literals updated to `.000Z` form.
  - `test_09_equipment_calibration.py` (`test_pass_calibration_restores_equipment`, line 152) — expected `calibration_valid_until` literal updated to `2026-11-28T00:00:00.000Z` (the other two calibration tests pick up the corrected `CALIBRATION_VALID_UNTIL_DEFAULT` constant).
  - `test_08_complaints_discipline.py` (`test_substantiation_voids_issued_invoice_and_credits_balance`) — added the missing `EXPECTED` name to the `from test_helpers import (...)` list; the constant exists in `test_helpers/constants.py` and is re-exported, but this file never imported it (`NameError`). The assertion itself (`outstanding_cents == EXPECTED["SINGLE_PRODUCT_100AC"]` = 945000 after issue, then 0 after substantiation-void) faithfully matches PRD §3.8's "credited by the invoice's `final_amount_cents`".

- **Fixes applied to `implementation/`**: none — the implementation was already PRD-faithful; every failure traced to test-side artifacts (stale zero-fraction expected literals contradicting PRD's three-fractional-digit timestamp mandate, plus one missing import).

**Orchestrator note (post-Step-7 verification):** all 8 `results.{1..8}.json` files on disk report `total: 85, passed: 85, failed: 0, skipped: 0`.

## Step 8: Finalize PRD — 2026-08-10T19:44:00.000Z

Confirmed byte-identical (diff -q silent, both 344 lines).

## Summary

**Outcome: PRD_FINALIZED.md is a byte-identical copy of PRD.md.** Every `<step_7_diff>` item turned out to be a pure test-side artifact — stale expected literals contradicting an already-verbatim PRD rule, plus one missing import — with zero PRD silence or PRD/impl mismatch revealed.

### Line counts
- PRD.md: 344 lines; PRD_FINALIZED.md: 344 lines; delta: 0 lines, 0.0%.

### Changes
None. No inserts, no revisions.

### Per-item verification (in lieu of per-edit search log, since no edits were committed)

For each diff item I identified the subject, enumerated every implementation path touching that subject, and confirmed the PRD already describes the implementation behavior verbatim:

1. **Item: `CALIBRATION_VALID_UNTIL_DEFAULT` / `REI_UNTIL_STANDARD` `.000Z` fix (test_helpers/constants.py)**
   - (a) Subject: wire format of `calibration_valid_until` and `rei_until` in responses.
   - (b) Paths enumerated: `workspace/implementation/util.py:61-69` (`_iso`/`iso` — the sole timestamp formatter, always `%Y-%m-%dT%H:%M:%S.` + `{:03d}` + `Z`); `domain.py:36-46` (`DT_FIELDS` covering every datetime field on every entity, including `calibration_valid_until` and `rei_until`); `domain.py:76-88` (`serialize` routes all datetime fields through `iso()`); `routes_people.py:141` (`calibration_valid_until = performed_at + 180 days`, matches PRD §3.3); `routes_work.py:359-362` (`rei_until = max(existing, completed_at + max rei_hours)`, matches PRD §3.5).
   - (c) No wording change: PRD §2.4 line 84 already states verbatim "Timestamps throughout the API are ISO 8601 UTC strings with three fractional digits" — the impl conforms; the test constants were stale.

2. **Item: `test_04` / `test_05` / `test_06` / `test_09` expected-literal `.000Z` fixes (`scheduled_start`, `started_at`, `completed_at`, `rei_until`, `calibration_valid_until`)**
   - (a) Subject: wire format of work-order, record, field, and equipment timestamps.
   - (b) Paths enumerated: same single formatter `util.py:61-63` plus `domain.py:43-44` (`work_order` and `application_record` DT_FIELDS include `scheduled_start`/`started_at`/`completed_at`); `store.py:12` (initial clock `2026-05-01T00:00:00Z` with zero microseconds, serialized as `.000Z`); `routes_registry.py:23` (`current_utc` via `iso()`); `util.py:72-73, 120-124` (envelope `api_request_timestamp`, covered separately by PRD §2.2 line 45).
   - (c) No wording change: same verbatim PRD §2.4 rule covers all of them.

3. **Item: missing `EXPECTED` import in `test_08_complaints_discipline.py`**
   - (a) Subject: substantiation-void credit semantics (`outstanding_cents` credited by `final_amount_cents`).
   - (b) Paths enumerated: `routes_compliance.py:126-139` (substantiation cascade voids DRAFT/ISSUED invoice; credits balance only when ISSUED, with `touch(cust)`); parallel void path `routes_compliance.py:232-246` (manual void, identical credit rule); issue path `routes_compliance.py:203-206`; pay path `routes_compliance.py:225`; `routes_registry.py:43` (balance starts at 0); `routes_work.py:188` (schedule-time credit gate).
   - (c) No wording change: PRD §3.8 ("credited by the invoice's `final_amount_cents` with the Customer's `version` incrementing") and §2.10 describe all enumerated paths verbatim. The failure was a `NameError` from a missing test import, not a behavioral question.

The deliverable `workspace/PRD_FINALIZED.md` exists and is verified byte-identical to `PRD.md`.

## Step 9: Complete PRD — 2026-08-10T20:01:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1112_custom_application_spray_service/workspace/PRD_COMPLETED.md` produced as a minimal patch over the source.

## Summary

**Source vs. output:** `PRD_FINALIZED.md` (byte-identical to `PRD.md`): 344 lines / 50,559 chars → `PRD_COMPLETED.md`: 349 lines / 56,424 chars. Char delta: **+5,819**. Diff touches 19 paragraphs/table-rows; no sections added or removed.

**Counts:** ambiguity-pins: 29 — mismatch-revisions: 4 (items 17, 24, 29, 32/33 below; 32/33 counted as one logical revision of the hop-two/three passage).

**Changes** (each verified against the impl line noted):

- §2.2 — insert — ambiguity — error envelope also covers unknown path `ERR_NOT_FOUND` 404, unsupported method `ERR_NOT_FOUND` 405, unexpected fault `ERR_INTERNAL` 500 — `app.py:48-60`
- §2.3 — insert — ambiguity — limit/offset bounds enforced via `ERR_VALIDATION` (not clamped); sort ties break by creation order (weather feed: later-created first); `total_count` = full filtered size; `has_more` ⟺ offset+page size < total_count — `util.py:132-141, 288-314`
- §2.4 — insert — ambiguity — mutable resources born with `version` 1 and `updated_at` = `created_at`; offset-less datetimes read as UTC, sub-second components discarded — `domain.py:54-60`, `util.py:76-89`
- §2.5 — revise — ambiguity — clock endpoint *sets* the clock with no monotonicity constraint; envelope `api_request_timestamp` is wall-clock, excepted from the logical clock — `routes_registry.py:18-23`, `util.py:72-73, 120-124`
- §2.9 — insert — ambiguity — `ERR_STALE_VERSION` runs immediately after the state tier (6); checks consuming a parsed body field or loaded target presuppose those steps (malformed body → `ERR_VALIDATION`, missing target → `ERR_NOT_FOUND`, ahead of ownership/segregation checks) — `routes_rx.py:83-92`, `routes_work.py:219-238`, `routes_records.py:43-49`, `routes_compliance.py:216-223`
- §3.1 — insert — ambiguity — Customer: non-empty `name`/`billing_email`; `rate_per_acre_cents`/`credit_limit_cents` non-negative integers, zero allowed — `routes_registry.py:34-37`
- §3.1 — insert — ambiguity — Field: non-empty `label`/`crop`, positive-number `acres`, non-negative-integer `buffer_clearance_ft` — `routes_registry.py:76-79`
- §3.1 — insert — ambiguity — Product: non-empty strings; `rei_hours`/`required_buffer_ft`/`unit_cost_cents` non-negative ints; `max_wind_mph`/`markup_pct` non-negative numbers; temps unrestricted — `routes_registry.py:124-136`
- §3.1 — insert — ambiguity — compatibility self-pair is `ERR_VALIDATION`; duplicate-pair check runs after product existence (duplicate naming a missing product → `ERR_NOT_FOUND`) — `routes_registry.py:163-171`
- §3.2 — insert — ambiguity — creation rejects `valid_from` > `valid_to` (`ERR_VALIDATION`); equal endpoints allowed — `routes_rx.py:28-29`
- §3.2 — insert — ambiguity — only `DRAFT` approvable; approving `APPROVED`/`SUPERSEDED` → `ERR_INVALID_STATE` — `routes_rx.py:86-87`
- §3.3 — insert — ambiguity — `license_categories` entries must be valid categories; array may be empty — `routes_people.py:30-36`
- §3.3 — insert — ambiguity — `tank_capacity_gal` must be a positive integer — `routes_people.py:85`
- §3.3 — insert — ambiguity — calibration `target_gpa` positive, `measured_gpa` non-negative — `routes_people.py:115-116`
- §3.3 — insert — ambiguity — `FAIL` on an already-`CALIBRATION_DUE` unit leaves equipment untouched (no version bump) but the schedule-revert cascade still runs — `routes_people.py:144-150`
- §3.4 — insert — ambiguity — no prescription↔field cross-check at intake; gates read field facts from the work order's field, product/window facts from the prescription — `routes_work.py:76-114, 165-184`
- §3.4 — revise — mismatch — scheduling gate bullet: nonexistent applicator → `ERR_NOT_FOUND`, inactive → `ERR_APPLICATOR_NOT_ACTIVE` (PRD had conflated both into the latter) — `routes_work.py:156-158, 169-170`
- §3.4 — insert — ambiguity — reschedule: replacement `applicator_id`/`equipment_id` explicitly null counts as absent — `routes_work.py:210-211`
- §3.5 — insert — ambiguity — freshest-observation tie-break extends past `created_at` to creation order; empty feed fails freshness as `ERR_OBSERVATION_STALE` at start and resume — `domain.py:196-200`, `routes_work.py:288-291, 317-320`
- §3.5 — revise — ambiguity — weather-post cascade evaluates the feed's freshest observation (not necessarily the new reading); stale freshest counts as envelope violation — `routes_people.py:197-208`
- §3.5 — insert — ambiguity — completion increments Field `version` whether or not `rei_until` actually moved — `routes_work.py:357-363`
- §3.6 — insert — ambiguity — record born with `returned_note`/`certified_by_user_id` null; whitespace-only return note counts as empty — `routes_work.py:353-354`, `util.py:197-201`
- §3.7 — revise — mismatch — any `Applicator`-role caller may record a disposal; not restricted to the assigned applicator — `routes_records.py:102-104` (no assignment check)
- §3.7 — insert — ambiguity — off-kind field optional on both kinds (stored null when absent); required `manifest_no` non-empty; supplied `disposal_field_id` must reference an existing Field; field-match rule applies only to `FIELD_DISPOSAL` — `routes_records.py:109-130`
- §3.8 — insert — ambiguity — complainant `X-User-ID` must resolve to an existing Customer (`ERR_NOT_FOUND`); `description` non-empty; filing exactly 30 days after completion is within the window — `routes_compliance.py:25, 30-31, 35-37`
- §3.8 — revise — mismatch — invoice hold applies while complaint is `FILED` or `INVESTIGATING`, but reinstatement is blocked only while `INVESTIGATING` (PRD had both freezes under FILED-or-INVESTIGATING) — `routes_people.py:67-70` vs `routes_compliance.py:199-201`
- §3.8 — insert — ambiguity — `findings_note` required non-empty on substantiate and dismiss — `routes_compliance.py:94, 149`
- §3.8 — insert — ambiguity — 365/90-day rolling windows inclusive at the boundary; penalty weight lands even on already-`SUSPENDED`/`REVOKED` applicators — `routes_compliance.py:104-110`
- §3.8 — revise — mismatch — rolling ≥ 10 revokes directly from `ACTIVE` or `SUSPENDED` (PRD pinned revoke only from `SUSPENDED`); `SUSPENDED` below 10 unchanged; score update bumps Applicator `version` once and a license transition bumps it again; hop three runs only when a transition fired; `PAID` invoice untouched by the void cascade — `routes_compliance.py:113-125, 132-139`
- §4 — revise — ambiguity — enumerated exact list-filter parameters on all 9 list endpoints (fields, compatibility-rules incl. named-side-literal matching, prescriptions, calibration-records, work-orders, application-records, rinsate-records, drift-complaints, invoices) — list comprehensions in each routes file
- §5 — insert — ambiguity — added `ERR_INTERNAL` | 500 row — `app.py:56-60`

**Notable finding:** the two genuine PRD-vs-impl contradictions were the §3.8 reinstatement freeze scope and the §3.8 hop-two revocation path (impl revokes `ACTIVE` applicators directly at rolling ≥ 10 and double-bumps the applicator version on transition); both revised to match impl. Deliberately left unpinned: unreachable corners (substantiation with a missing applicator entity), JSON number representation details, and non-`/api` paths.

**Orchestrator note (post-Step-9 verification):** `workspace/PRD_COMPLETED.md` exists (349 lines, 56,424 bytes); all 8 `results.{1..8}.json` sweep files report `passed == total == 85`; pipeline complete.
