# Worklog — task_1972_water_treatment_chemical_service

## Step 1: Create Task Directory — 2026-08-15T04:05:48.411Z

Pre-completed by the invoking pipeline: `tasks/task_1972_water_treatment_chemical_service/` and `tasks/task_1972_water_treatment_chemical_service/workspace/` already existed; verified present. No index scan performed per invocation instructions. Difficulty directive from user: "Generate task hard than expert level!"

## Step 2: Generate Scaffold — 2026-08-15T04:41:43.160Z

Note: the first subagent run stopped mid-design without writing files (output-limit cutoff during inline deliberation); it was resumed via SendMessage with an instruction to write files immediately, and completed successfully.

All three files are written, parse cleanly, and pass `scaffold_lint.py` with a clean verdict. Final summary:

## Summary — task_1972_water_treatment_chemical_service

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1972_water_treatment_chemical_service/`):
- `SCAFFOLD.yaml` (§1.0–§1.7; no difficulty/corner keys) — 2064 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`) — 1383 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`) — 2277 lines

**Counts:**
- Entities: 16 (CustomerAccount, SystemAsset, ProgramDesign, ChemicalProduct, FeedStation, TelemetryReading, TestRoute, RouteStop, WaterTestResult, CorrectiveAction, CouponRack, CorrosionCoupon, LegionellaRiskPlan, BlowdownEvent, DeliveryOrder, Invoice)
- State machines: 12 entries (including posture as a derived parallel dimension on SystemAsset and the SUPERSEDED auto-transition)
- Calculations: 9 (LSI dual-variant, feed-rate setpoint with nested min/max + mode branch, circular-looking blowdown/CoC water-balance with pinned evaluation order, coupon mpy annualization, consecutive-violation threshold, forward-looking inventory depletion, invoice pricing with pinned per-line rounding, two interval-overlap rules with different semantics)
- Validation rows: 15 priority tiers; Errors: 42; Endpoints: 89 (all unique method+path); Roles: 4 (PlatformAdmin/AccountManager/WaterChemist opaque + CustomerContact entity_backed:CustomerAccount), segregation-of-duties role model; OCC concurrency rules: 3
- **§1.8 difficulty instances: 19** — all 9 rules ≥2, combinatorial_formula has 3 (one per mode a/b/c)
- **§1.9 corner instances: 53** (52 active + 1 excluded_because stub) across all 9 claim-extraction-guide sections

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
950 calls scanned across both design files, 0 violations. Additional manual audits passed: no forbidden concurrency vocabulary, zero unbound `${var}` placeholders, all 72 instance names unique, every error code referenced, every enum state produced by a transition, all `grounds:` resolve.

**Notable harder-than-expert design decisions:**
- **Depth-4 transitive cascade**: 3rd consecutive OUT_OF_RANGE WaterTestResult → auto-create PENDING CorrectiveAction → approve/apply mutates FeedStation setpoint → depletion projection recompute → auto-drafted DeliveryOrder; verified with computed literals (setpoint 24.9206 → 27.4206; consumed 40.0009 gal → inventory 65.9991 gal → depletion 11.55 days < 14-day alert threshold).
- **Sharp numeric boundaries**, all literals executed via Python: LSI stored 2.50 (ph 8.6211) classifies SCALE_FORMING vs 2.49 (ph 8.6111) BALANCED; coupon exposure 30 days RELIABLE (mpy 3.148) vs 29 UNRELIABLE (3.257); escalation at exactly 3 (not 2); dispatch at exactly scheduled_for allowed; half-open visit windows vs closed+7-day-buffer coupon intervals (adjacency allowed on one resource, forbidden on the other).
- **Dual-variant calcs on different entity domains**: LSI provisional (TDS = conductivity × 0.7) vs finalized (lab TDS) on WaterTestResult (0.79 vs 0.76 for identical field inputs); PRODUCT vs SERVICE_CONTRACT invoice pricing on Invoice (54945 vs 123455 for identical deliveries); nested rounding pinned per-line-then-sum (4335 vs the forbidden 4334).
- **OCC true races only**: accept-design, approve-corrective-action, schedule-delivery — each write endpoint takes `expected_*_version` and bumps parent version; all recipe version inputs are captured `${var}`s, never literals.
- **Compliance backbone**: cyclic ProgramDesign revision loop (revision_number increments), cyclic LegionellaRiskPlan with clock-driven VALIDATION_DUE → 14-day grace → DELINQUENT, posture-driven gating (FROZEN asset blocks arrivals/approvals/results), SoD (approver must differ from recorded_by_user_id), priority conflicts on different category pairs (state-vs-fiscal, state-vs-referential).
- Logical clock endpoint with the mandated fixed default `2026-08-01T00:00:00Z`, enabling deterministic time-gated setups everywhere.

## Step 3: Copy Shared Files — 2026-08-15T04:41:43.160Z

Copied `./INSTRUCTION.md` → `tasks/task_1972_water_treatment_chemical_service/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T04:55:48.271Z

All contracts pass. The PRD is complete and verified.

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1972_water_treatment_chemical_service/workspace/PRD.md` — 398 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC & identity semantics · 2.2 API Response Structure (byte-verbatim fixed block, verified against source) · 2.3 Pagination · 2.4 Logical Clock & Scheduled Sweeps · 2.5 Common Resource Properties · 2.6 Validation Pipeline (all 15 priority tiers, in order) · 2.7 Optimistic Concurrency Control (all 3 OCC rules) · 2.8 Asset Posture (derived compliance dimension) · 2.9 Units, Precision & Rounding · 2.10 Nested Path/Body Reference Resolution
- §3 Business Logic (9 subsections): 3.1 Accounts · 3.2 Assets & Program Design cycle · 3.3 Catalog/Feed Stations/Telemetry · 3.4 Routes/Stops/Results · 3.5 Escalation & Corrective Actions · 3.6 Coupons & Racks · 3.7 Legionella Plans · 3.8 Blowdown & Water Balance · 3.9 Deliveries/Tote Exchange/Invoicing
- §4 Endpoint Definitions — 89-row table (4 columns), matches scaffold endpoint count exactly
- §5 Error Code Catalogue — 42-row table (2 columns), status parity verified against scaffold

**Coverage audit (hard contracts):**
- Contract 1 (field names): 99 entity fields, 76 endpoint input identifiers, 15 path params, plus OCC fields, envelope fields, and report output fields — all present verbatim in backticks; 0 missing (two-pass: first pass found `rack_id`, `route_id`, `stop_id` absent; fixed by targeted sentences in §3.4 and §3.6; pass 2 clean).
- Contract 2 (rules): all 15 validation tiers expressed as an ordered pipeline with error-id pairing and `applies_to` scopes; 3/3 OCC rules with write endpoint + `expected_<parent>_version` + `ERR_STALE_VERSION`/412; all 12 state machines' transitions (from/to/preconditions/side effects) rendered; all 9 calculations expressed as reconstruction-grade prose with constants embedded (0.0085, 0.0002, 3785.411, 1440, 22300, 86400, 0.7, 2.5/−2.5 inclusive bands, 13.12/34.55/9.3/0.4, baseline CoC 3.0, 14-day alert/grace, 30-day reliability, 30-day overdue, 2.0 g deposit allowance); all cross-entity cascades (suspend→cancel+freeze, accept→supersede/freeze-CoC/recompute, apply→clamp/reset/auto-draft, void→decrement/decline, confirm-delivery/close→inventory ledger, clock→dual sweeps) stated; sibling branches rendered with equal density (schedule PENDING vs FAILED_DELIVERY asymmetry explicitly preserved; cancel from 3 states; plan suspend from 3 states; PRODUCT vs SERVICE_CONTRACT; CONTINUOUS vs SHOT_FEED; provisional vs finalized LSI).
- Contract 3 (§3 path purity): 629 backticked tokens in §3 scanned, 0 path/method violations.
- Every one of the 42 error IDs is mentioned in §2/§3 prose; §5 table has exact HTTP status parity with the scaffold.

**Scaffold ambiguities resolved in prose (flagged for the record):**
1. *FeedStation creation trigger with no ACCEPTED design:* scaffold lists creation as a `feed_rate_setpoint` trigger but the input set requires an ACCEPTED design's `inhibitor_target_ppm`. PRD states the three triggers and input set faithfully and notes the station starts with the field defaults (setpoint 0, null projection) without inventing a no-design outcome.
2. *SHOT_FEED arithmetic:* the scaffold's shot branch (×1440 then ÷1440) is numerically identical to CONTINUOUS; PRD transcribes both formulas exactly as specified, preserving the operand order.
3. *Blowdown `occurred_at` in the future:* the catalog pins `ERR_NON_MONOTONIC_EVENT` to the monotonic violation only; PRD states both constraints (not-after-now, strictly-after-previous) under the temporal tier without inventing a new error ID.
4. *Account-close cascade depth:* scaffold lists only "assets → DECOMMISSIONED" for close (no coupon/stop preconditions, unlike the decommission endpoint); PRD renders close as unconditional decommissioning and keeps the endpoint's own guards/cascades separate.
5. *`span_days` pinned at 7:* the projection uses a fixed 7-day divisor whenever any window reading exists (not the actual reading span); PRD states this exactly.
6. *Checker artifact:* `STAINLESS_` "missing" was a YAML enum-split artifact; both `STAINLESS` (metallurgy) and `STAINLESS_304` (alloy) are present in the PRD.

## Step 5: Generate Unit Tests — 2026-08-15T05:31:54.295Z

Generation complete. Summary:

## Files written

**`test_helpers/`** (9 files, under `/home/ubuntu/github/CodingPRD/tasks/task_1972_water_treatment_chemical_service/test_helpers/`):
- `types.py` — 17 status enums + 16 entity TypedDicts; the three append-only records (TelemetryReading, WaterTestResult, BlowdownEvent) correctly omit `updated_at`/`version`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (all `/wt/...`, incl. clock)
- `api_errors.py` — all 42 error IDs with HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity asserters (append-only variants never demand `version`/`updated_at`) + invariant checkers
- `factories.py`, `constants.py` (escalation 3, buffer 7d, grace 14d, reliable 30d, baseline CoC 3.0, etc.), `test_users.py` (opaque role constants + `make_customer_contact_headers(account_id)` for the entity-backed role)
- `fixtures.py` — composite helpers: `setup_commissioned_asset`, `setup_delivery_ready`, `create_proposed/accepted_design`, `create_published_route`, `record_out_of_range_sequence`, `setup_pending_corrective_action`, `deliver_and_close_order`, `create_and_issue_invoice`

**`test_suite/`** — `conftest.py` + 11 test files (`test_01_entity_basics` … `test_11_delivery_invoicing`).

## Test counts
- **Difficulty (queue A): 36 tests** covering 18/19 instances at exactly 2 tests each (all computed literals verified numerically before emission: LSI 0.79/0.76 and 2.50/2.49, setpoints 38.3273→24.9206→27.4206, invoice 54945/123455 and rounding 4335, blowdown 12240/5832/2832, mpy 3.148/3.257, inventory 65.9991, telemetry rate 0.7548).
- **Corner (queue B): 52 tests** — every non-stub instance has exactly ≥1 test. The one stub (`error_catalog_triggerability_stubs`) was not translated; note its `difficulty_instance` pointer partially mis-references two corner instances (`segregation_of_duties_same_user_approve_rejected`, `schedule_in_past_rejected`) instead of difficulty instances — a corner-design metadata bug, harmless since stubs emit nothing.
- **Total: 88 tests.**

## Skipped instances (PRD-first filter)
- `Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_result_recording` — not uniquely derivable: the recipe's payload asset is a never-commissioned BOILER, so a faithful PRD reader resolving "the asset" of §3.4's result-recording guards to the payload asset would return `ERR_ASSET_NOT_IN_SERVICE` (or defer to tier-13 `ERR_ASSET_MISMATCH`) instead of the asserted `ERR_ASSET_FROZEN`. No weakening emitted; gap left as a gap.

## Adaptations made during faithful translation (asserts unchanged)
- `coupon_exposure_exactly_30_days_is_reliable`: reordered removals (29-day coupon removed at 08-30, then clock advanced to 08-31 for the 30-day coupon) to avoid a backward clock set the PRD never licenses ("may advance the clock").
- `telemetry_window_excludes_readings_older_than_7_days`: advanced the clock to 08-08T12:00 before posting the second reading (the recipe as written would hit `ERR_TELEMETRY_FUTURE`).

## Stage-2 self-check results
- **Tag audit**: 88/88 tests carry exactly one terminal `Design:` line; all tags resolve to real instances; corner coverage 52/52; difficulty coverage 18/19 (the 19th is the deliberate skip above); stub untranslated.
- **Verbatim citation pass**: all 144 quoted rule sentences (≥6 words) survive literal grep of `workspace/PRD.md`.
- **Import smoke check**: `py_compile` clean on all 21 files; all 11 test modules import successfully under `PYTHONPATH=<task_dir>`.
- No `skip`/`skipif`/`xfail` markers; no scaffold/table references in generated code comments.

## Step 6: Generate Implementation — 2026-08-15T05:31:54.295Z

Implementation complete. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1972_water_treatment_chemical_service/workspace/implementation/`)

- `start.sh`, `requirements.txt` (flask), `app.py` (entry point, blueprint registration, envelope-wrapped error handlers, before-request auth)
- `db.py` (16 empty-at-boot dict stores, logical clock pinned at `2026-08-01T00:00:00Z`, id/seq/timestamp helpers, `touch()` = updated_at+version bump)
- `errors.py` (all 42 catalog error IDs + `ERR_ASSET_DECOMMISSIONED`, which the PRD §3.3/scaffold state machine reference though absent from the §5 table)
- `response.py` (exact envelope: `meta.api_request_id` (`req_` + 20 alnum), `api_request_timestamp` (3-frac ISO), `response_type`, `data`; error body `data.error_id`/`data.message`)
- `middleware.py` (tier-1 header presence, tier-2 role check against a full 89-entry (method, path-template) → roles map)
- `validate.py` (tier-4 FK resolution in declared input order, tier-5 shape/type/enum validation, pagination clamp 1–100/default 10, CustomerContact ownership/scope helpers)
- `calc.py` (all 9 calculations + posture derivation + clock sweeps)
- `serializers.py`, `helpers.py`
- 12 route modules: `routes_clock/accounts/assets/designs/products/stations/routes/results/racks/plans/orders/invoices`

## Endpoints: 89/89 implemented (verified against the §4 table; all registered in the roles map)

## Key organization decisions

- **State machines**: implemented per endpoint with pipeline-ordered checks — tier 5 shape → tier 6 transition legality → tier 7 cross-entity gates (in PRD-stated order, e.g. `ERR_PROGRAM_NOT_ACCEPTED` before `ERR_ACCOUNT_NOT_ACTIVE`) → tier 8 Legionella gate → tier 9 SoD → tier 10 field constraints → tier 11 temporal → tier 12 overlap → tier 13 referential → tier 14 fiscal → tier 15 OCC (three OCC writes: accept/approve/schedule).
- **Posture** is a pure derived function in `calc.compute_posture` (FROZEN > NON_COMPLIANT > WATCH > COMPLIANT from account-suspended / plan-SUSPENDED / plan-DELINQUENT / violation count), recomputed on every driver; bumps `version`/`updated_at` only on actual change.
- **Calculations**: LSI dual-variant (provisional TDS = conductivity×0.7; finalized = lab_tds; 2dp half-up; inclusive ±2.5 bands); feed-rate with pinned evaporation→drift→blowdown→mode-branch→clamp order (SHOT_FEED branch written literally as ×1440…÷1440, 4dp half-up); 7-day half-open `[now−7d, now)` depletion window with `recorded_at,created_at` ordering, null projection at rate 0; water balance with pinned 4-step order and 2dp half-up; coupon mpy 3dp + RELIABLE at exactly 30 days; escalation at `>= 3`; invoice per-line `Decimal` round-half-up then sum with PRODUCT/SERVICE_CONTRACT variants.
- **Overlaps**: route stops use half-open semantics (adjacency allowed, only SCHEDULED/ARRIVED participate); coupons use closed-interval + 7-day buffer (adjacency forbidden) — checked at tier 12, before the tier-13 `ERR_RACK_ARCHIVED`.
- **Cascades**: account suspend (orders→CANCELLED + assets→FROZEN), close (assets→DECOMMISSIONED only), accept (supersede siblings + freeze `target_coc` + recompute all station setpoints), decommission (stations→LOCKED_OUT + plan→SUSPENDED), apply (setpoint clamp + counter reset + 14-day-inclusive depletion auto-draft of one container), void (counter decrement + PENDING actions→DECLINED), route auto-complete, clock sweeps (plan `validation_due_at <= now` → VALIDATION_DUE; invoice strictly past `period_end`+30d → OVERDUE).

## start.sh contract

Guarded install (`if ! python3 -c "import flask"`), then `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000), foreground.

## Boot smoke-check

Launched via `bash start.sh` on PORT 19873: `ss` confirmed `0.0.0.0:19873` listener owned by `python3 app.py` directly (exec verified — no wrapper shell), clock-set returned `{"data":{"current_utc":"2026-08-10T00:00:00Z"},...}`, account list returned a correctly paginated empty array (store starts empty), then the process was killed cleanly. A ~40-assertion end-to-end functional pass additionally verified: LSI provisional/final values to the cent-digit, tier-6-before-tier-10 precedence, OCC 412s, ownership 403s, window conflict vs adjacency, escalation at the 3rd violation with SoD blocking the recorder, clamp behavior, container-multiple 422, schedule-past/too-early-dispatch 422, inventory credit/debit, SERVICE_CONTRACT invoice math (77000 + 25000 = 102000), overdue sweep boundary (ISSUED at exactly +30d, OVERDUE 1s later), plan suspend→FROZEN/return-to-draft→COMPLIANT, coupon mpy/rating/buffer-conflict, and blowdown monotonicity. All calculation checks passed exactly.

## Step 7: Run Tests and Iterate — 2026-08-15T06:05:00.000Z

Clean 8-round parallel sweep achieved: **88/88 passed in every round (8/8)**.

## Summary

- **Iterations run:** 2 (baseline sweep → fixes → verification sweep; plus one solo single-round run between them to isolate deterministic from flaky failures).

- **Tests deleted:** None. Every failing test traced to PRD-verbatim rules; no deletion was warranted.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1972_water_treatment_chemical_service/test_helpers/api_client.py` — set `api_client.session.headers["Connection"] = "close"` on the shared `requests.Session`. Why: the per-test-server harness SIGKILLs and restarts the server on the same port before every test; the session's keep-alive pool could hand a test a stale connection to the just-killed server generation, surfacing as flaky `ConnectionResetError(104)` mid-test under 8-way parallel load (this was the root cause of `test_lsi_classification_just_below_2_5_is_balanced` failing in rounds 2/6 and `test_close_account_with_unpaid_balance_rejected` in round 6 — both passed solo and in all other rounds). Transport robustness only; no assertion changed.

- **Fixes applied to `test_suite/`:** (both in `/home/ubuntu/github/CodingPRD/tasks/task_1972_water_treatment_chemical_service/test_suite/test_04_telemetry_inventory.py`)
  - `test_telemetry_reading_immutable_shape` — posted telemetry with `recorded_at=2026-08-01T01:00:00Z` while the logical clock read `2026-08-01T00:00:00Z`; the PRD-faithful implementation correctly rejected it with `ERR_TELEMETRY_FUTURE` (PRD §3.3: recorded_at "must not be later than the current clock"). Test bug: advanced the clock to the recorded instant before posting.
  - `test_telemetry_window_excludes_readings_older_than_7_days` — posted the in-window reading with `recorded_at` exactly equal to the evaluation clock. PRD §3.3 names the trailing window "half-open ... up to the current clock" without pinning which end is open (contrast §3.4, which says "inclusive/exclusive" explicitly), so a faithful `[now-7d, now)` implementer excludes a reading at exactly `now` and computes rate 0 while a `(now-7d, now]` implementer computes 0.7548 — unique-derivability collapse on that boundary. Per STEP 1c partial-coverage handling, kept the covered assertions (7-day exclusion, consumed/7 at 4dp, `last_telemetry_at`) and moved the reading to `2026-08-08T11:00:00Z`, strictly inside the window under every faithful endpoint convention.

- **Fixes applied to `implementation/`:** None — the implementation was PRD-faithful in all four failure cases; all bugs were in the test artifact layer.

Orchestrator note: the subagent removed its results files after the final sweep; I re-ran the full 8-round parallel verification sweep myself to confirm the claim and restore the artifacts — `results.{1..8}.json` all show passed: 88, failed: 0, total: 88 (SWEEP CLEAN), and now persist under `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-08-15T05:54:14.558Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1972_water_treatment_chemical_service/workspace/PRD_FINALIZED.md` is written with exactly one in-place revision.

## Summary

**Line/char counts:** PRD.md 397 lines / 63,730 chars → PRD_FINALIZED.md 397 lines / 63,965 chars. Line delta +0 (0.000%); char delta +235 (+0.369%). Diff is a single-sentence revision on line 186.

**Changes:**
- §3.3 (Product Catalog, Feed Stations, and Telemetry) — revise — the trailing seven-day telemetry window's endpoint convention was pinned to match the implementation: lower bound (seven days before the current clock) **inclusive**, upper bound (the current clock) **exclusive**, with the boundary consequences spelled out (a reading exactly at `now − 7d` is inside; a reading exactly at `now` is outside) — `implementation/calc.py:126-128` (`window_start <= r["recorded_at"] < current`).

**Candidate site (b) — `ERR_TELEMETRY_FUTURE`:** verified and deliberately left verbatim. PRD §3.3's "must not be later than the current clock" already uniquely determines the implementation's `vals["recorded_at"] > now()` rejection (`implementation/routes_stations.py:126`); a reading exactly at the clock is accepted under both. The Step 7 failure there was a pure fixture bug (test posted a future `recorded_at`), so no PRD edit was warranted. The `test_helpers/api_client.py` `Connection: close` fix is transport robustness, not PRD behavior — no edit.

**Per-edit pre-edit search log (the single edit):**
- (a) **Subject:** endpoint convention (open/closed bounds) of the trailing 7-day window used to compute `consumption_rate_gal_per_day`.
- (b) **Impl paths enumerated and read/grepped:** the sole window-membership filter `calc.py:126-128`; the rate derivation `calc.py:129-133`; all five `recompute_station` call sites — `routes_stations.py:138` (telemetry post), `routes_orders.py:175` (confirm-delivery), `routes_orders.py:207` (close), `routes_results.py:297` (corrective-action apply), `routes_designs.py:171` (design acceptance) — all funnel through the one centralized filter with no parallel window logic; the future-rejection path `routes_stations.py:125-128` (a reading at exactly `now` is accepted yet window-excluded — the edit speaks only to window membership, not acceptance, so no contradiction); `last_telemetry_at` assignment `routes_stations.py:139-140` (set regardless of window membership — untouched by the edit); ordering paths `calc.py:117` and `routes_stations.py:153` (ordering clause kept verbatim); `depletion_alert` `calc.py:157-162` (reads the derived projection, no independent window semantics); grep for `window_start`/`WINDOW_DAYS`/`recorded_at`/`TELEMETRY_FUTURE` across all of `implementation/` confirmed no other site touches the subject.
- (c) **Wording adjustment:** inserted boundary-consequence clause ("a reading recorded exactly seven days before the current clock falls inside the window, while a reading whose `recorded_at` equals the current clock exactly falls outside it") so the membership of both boundary instants is uniquely derivable, matching the observed Step 7 collapse (`[now−7d, now)` yields rate 0 for a sole at-`now` reading; `(now−7d, now]` yields 0.7548). No narrowing of any off-site path resulted — all five recompute callers exhibit identical semantics.

## Step 9: Complete PRD — 2026-08-15T06:10:48.906Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1972_water_treatment_chemical_service/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`.

**Size**: PRD_FINALIZED.md 397 lines / 64,378 chars → PRD_COMPLETED.md 400 lines / 67,338 chars; char delta **+2,960**. Diff is 20 hunks: 19 in-place sentence revisions + 1 table-row insertion. No new sections, no new paragraphs beyond one one-line clause under §2.5's bullet list.

**Counts**: 17 ambiguity-pins, 3 mismatch-revisions.

**Verification done before editing**: all 89 impl routes match the §4 table 1:1 (only `{id}` vs `{stationId}` param-naming style differs); all role assignments in `middleware.py` match the §4 Authorized Role(s) column; §5 statuses match `errors.py` for all pre-existing rows.

**Changes** (section — insert/revise — class — what changed — impl ref):

- §2.3 — insert — ambiguity — `limit`/`offset` are clamped (limit <1→1, >100→100, offset <0→0), non-integers fall back to defaults — `implementation/validate.py:110-128`
- §2.4 — revise — mismatch — coupon `installed_at` is NOT clock-validated (only conflict/exposure rules of §3.6 constrain it); other client timestamps keep their clock rules — `implementation/routes_racks.py:80-87` (no clock check)
- §2.5 — insert — ambiguity — `version` starts at 1 at creation; `updated_at` initialized to `created_at` — `implementation/db.py:111-121`
- §2.6 tier 7 — insert — ambiguity — added the bring-online gate: station's asset `DECOMMISSIONED` → `ERR_ASSET_DECOMMISSIONED` — `implementation/routes_stations.py:86-88`
- §2.6 tier 10 — revise — mismatch — split `quantity_gal` codes: non-positive → `ERR_FIELD_CONSTRAINT`; positive non-multiple → `ERR_QUANTITY_NOT_CONTAINER_MULTIPLE` (old sentence assigned the special code to "not a positive whole multiple", which covers non-positives) — `implementation/routes_orders.py:46-50`
- §2.8 — insert — ambiguity — posture precedence pinned: `FROZEN` > `NON_COMPLIANT` > `WATCH` > `COMPLIANT` with exact driver conditions — `implementation/calc.py:238-250`
- §3.1 — revise — ambiguity — account closure performs only the asset status move; the §3.2 decommission cascade (station lockout, plan suspension, posture recompute) does NOT run on closure — `implementation/routes_accounts.py:92-98`
- §3.2 — insert — ambiguity — record-survey payload must carry `survey_notes` (required) — `implementation/routes_designs.py:74`
- §3.3 — insert — ambiguity — `container_size_gal` pinned strictly positive — `implementation/routes_products.py:28-29`
- §3.3 — revise — ambiguity — setpoint computed at creation only when the asset already has an `ACCEPTED` design, else stays 0; feed-station list supports `asset_id` and `product_id` filters — `implementation/routes_stations.py:50-53,61-66`
- §3.3 — revise — ambiguity — depletion alert = projection at or before clock+14d (past projections qualify; null never) — `implementation/calc.py:157-162`
- §3.4 — insert — ambiguity — test-route list supports `account_id` and `status` filters — `implementation/routes_routes.py:49-54`
- §3.4 — insert — ambiguity — `range_status` judgement pinned: OUT_OF_RANGE iff pH strictly outside [`ph_min`,`ph_max`], conductivity strictly above max, or inhibitor strictly below target; IN_RANGE when no ACCEPTED design exists — `implementation/routes_results.py:32-42`
- §3.4 — insert — ambiguity — `ERR_LAB_TDS_REQUIRED` enforced with request-shape checks ahead of transition legality — `implementation/routes_results.py:178-183`
- §3.5 — revise — ambiguity — escalation at count ≥3 auto-creates a PENDING action on the 3rd AND every further consecutive violation; target station = asset's earliest-created feed station — `implementation/routes_results.py:117-125,23-29`
- §3.5 — revise — ambiguity — apply-cascade alert references the §3.3 depletion-alert rule (keeps the two alert phrasings consistent) — `implementation/calc.py:157-162`, `implementation/routes_results.py:307`
- §3.8 — revise — ambiguity — water-savings report shape pinned: rows in an `events` array carrying `event_id`, `occurred_at`, `evaporation_gal`, `achieved_coc`, `saved_gal` — `implementation/routes_assets.py:200-227`
- §3.9 — revise — ambiguity — `quantity_gal` code split mirrored in prose (matches tier-10 fix) — `implementation/routes_orders.py:46-50`
- §3.9 — revise — ambiguity — SERVICE_CONTRACT fee taken from the ACCEPTED design of the line set's earliest-created order's station's asset; 0 when the line set is empty or that asset has no accepted design — `implementation/calc.py:211,222-227`
- §5 — insert — mismatch — added missing `ERR_ASSET_DECOMMISSIONED | 409 Conflict` row (suspect area (a) confirmed: code defined at `implementation/errors.py:57`, emitted at `implementation/routes_stations.py:87`, referenced by §3.3 prose, absent from the table; §5 now covers all 43 impl codes)

All other suspected areas checked and found already aligned: pagination bounds wording (now clamp-pinned), the §3.3 trailing-7-day window (already pinned in PRD_FINALIZED), station setpoint/inventory/depletion formulas, both interval-overlap regimes, sweep boundaries (`validation_due_at <= clock`, invoice strictly past period_end+30d), response envelopes, and all field-range constraints.

