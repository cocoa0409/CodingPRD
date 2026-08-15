# Worklog — task_1446_tanker_bulk_liquid_trucking

## Step 1: Create Task Directory — 2026-08-13T07:55:00.000Z

Task directory `tasks/task_1446_tanker_bulk_liquid_trucking/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions. No index scan performed, no other task directory touched.

## Step 3: Copy Shared Files — 2026-08-13T07:56:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1446_tanker_bulk_liquid_trucking/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate Scaffold — 2026-08-13T09:16:30.000Z

Scaffold generation complete for task_1446_tanker_bulk_liquid_trucking. Lint verdict (verbatim, final run):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared: 77 · §1.1 entities: 15 · §1.8 instances: 18 · §1.9 instances: 65 · calls scanned: 919
```

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1446_tanker_bulk_liquid_trucking/SCAFFOLD.yaml` — 1189 lines (§1.0–§1.7; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1446_tanker_bulk_liquid_trucking/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 647 lines (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1446_tanker_bulk_liquid_trucking/SCAFFOLD_CORNER_DESIGN.yaml` — 1393 lines (single key `scaffold_corner_design`)

**§1.1–§1.7 counts**: 15 entities (Customer, Product, CompatibilityRule, TankTrailer, Driver, WashBay, TankWashCertificate, LoadingRack, Shipment, MeterTicket, DeliveryTicket, RetainSample, SpillResponsePlan, SpillIncident, DedicatedTrailerAgreement) · 11 state machines (cyclic: Shipment LOADING↔PLANNED; SpillIncident REPORTED↔UNDER_REVIEW + reopen; SpillResponsePlan APPROVED↔SUSPENDED; lazy EXPIRED transitions) · 2 OCC concurrency rules (shipment patch, agreement patch; both 412 ERR_STALE_VERSION with `${var}`-only version payloads) · 8 calculations (net-60 temp correction w/ observed-vs-net60 variants; provisional-vs-final billing with pinned per-line rounding; capped allowed-loss `min`; axle/GVWR/3%-sum compliance; wash-rank resolution; credit exposure; month-close shortfall with ceil floor; spill severity tiers) · 11 ordered validation priority rows (auth → authz → existence → shape → OCC → state → safety → temporal → constraint → referential → fiscal) · 77 endpoints (flat topology under `/bulk-liquid`, filtered-list FK reverse-reachability everywhere, `/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`) · 64 errors (all referenced) · 7 roles (5 opaque + `Driver`/`CustomerRep` entity-backed; segregation-of-duties: meter-closer ≠ weight-verifier, incident-closer ≠ reopener).

**§1.8**: 18 instances, exactly 2 per rule × 9 rules; every numeric assert pre-computed (e.g., net60 4860.0 vs observed 5000.0; final bill 516106 ≠ provisional 535000; per-line rounding 28014 ≠ sum-first 28013; allowed-loss cap 50.0; axle equality at 34000 lb; variance equality at 15.0 gal). Cascades: delivery-close → ticket → shipment VARIANCE_REVIEW → agreement flag (depth 3); cert revoke → cert VOIDED → shipment DRAFT → trailer AVAILABLE (depth 3).

**§1.9**: 65 active instances across all nine guide sections + 5 `excluded_because` stubs (all resolve to named §1.8 instances); covers creation/defaults/required-fields/enums/pagination, invalid-transition & terminal lockdowns, calc precision/boundaries/input-set filtering, 13 validation triggers (incl. priority-ordering existence-beats-state), every remaining error code, 6 RBAC denial/identity instances, OCC/derived-field/lazy-expiry/SoD layer claims, and immediate-consistency. All 88 instance names unique across the union; zero forbidden concurrency vocabulary.

## Step 4: Generate PRD — 2026-08-13T09:41:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1446_tanker_bulk_liquid_trucking/workspace/PRD.md`. The two forbidden design files were never opened.

**Output**: `workspace/PRD.md` — **359 lines**

**Section list**:
- §1. Introduction (2 paragraphs)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control · 2.2 API Response Structure (byte-verbatim canonical block, verified) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock and Lazy Expiry · 2.6 Units, Precision, and Rounding · 2.7 Optimistic Concurrency Control · 2.8 Validation Pipeline, Ordering, and Resource Existence · 2.9 Cascading Consistency and Compensating Releases
- §3. Business Logic & Workflows (scattering zone, 8 subsections organized chronologically along the load lifecycle)
  - 3.1 Master Data · 3.2 Compatibility & Tank Wash Certification · 3.3 Shipment Creation/Revision/Planning · 3.4 Loading at the Rack · 3.5 Delivery, Variance & Retain Samples · 3.6 Billing, Credit Exposure & Reconciliation · 3.7 Spill Plans & Incident Reporting · 3.8 Dedicated-Trailer Program
- §4. Endpoint Definitions (4-column table, 77 rows)
- §5. Error Code Catalogue (2-column table, 64 rows)

**Coverage audit (all PASS)**:
- **Entities**: 15/15 covered in prose; **entity fields**: 100/100 present in backticks
- **Request-only inputs** (`expected_shipment_version`, `to_iso8601`, `steer_lb`, `retain_sample_ml`, `reason`, `settlement_month`, etc.): 10/10 present
- **Query params**: 19/19 present (§2.3 pagination + §4 filter sentence); **path params**: 14/14 present inside backticked §4 paths
- **State machines**: 11/11 — all 47 transitions expressed with from/to states, preconditions paired to error IDs, and side effects including multi-hop cascades (cert revoke → shipment revert → trailer release; delivery variance → agreement flag → auto-suspend at 2)
- **Calculations**: 8/8 fully translated to pseudocode-free prose with constants embedded (48/96/168 h wash validity, 15000¢ rack fee, 4% surcharge, 5.0+0.02/mile capped at 50.0 loss, 3% weight tolerance, 0.8 commitment floor with 25000¢/load fee, 10/100 gal severity tiers with 12 h deadline, 90-day retention, 365-day plan validity, 60 °F reference)
- **Validations**: 11/11 priorities expressed as an explicit ordered pipeline in §2.8 (auth → RBAC → existence → shape → OCC → state → safety → temporal → uniqueness/dedication/SoD → referential → fiscal, with the "credit gate runs last" consequence stated)
- **Concurrency rules**: 2/2 fully expressed (write endpoint capability + `expected_<parent>_version` + `ERR_STALE_VERSION` 412)
- **Endpoints**: 77/77 in §4 table; side effects scattered in §3
- **Errors**: 64/64 in §5 table and each mentioned with its trigger condition in §2/§3
- **Roles**: 7/7 named with exact spelling; identity semantics translated per role (Driver→entity-backed Driver id, CustomerRep→entity-backed Customer id, five opaque roles)
- **Contract 3 (§3 path purity)**: 539 backtick tokens scanned, 0 path/method violations
- **Enum/state values**: all 51 UPPERCASE values present verbatim, including terminal-state mentions
- **No-pseudocode check**: no operator-syntax tokens in §2/§3 prose; no fuzzy/approximating words

## Step 5: Generate Unit Tests — 2026-08-13T10:12:00.000Z

All generation and audits are complete. Final summary:

**Output** (under `/home/ubuntu/github/CodingPRD/tasks/task_1446_tanker_bulk_liquid_trucking/`):

- **`test_helpers/`** — 9 files (1,620 lines): `__init__.py` (barrel), `types.py` (13 entity TypedDicts + 15 enums; all entities carry id/created_at/updated_at/version per PRD §2.4), `api_client.py` (66 methods, one per PRD §4 endpoint), `api_errors.py` (66 error IDs with HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py` (billing/loss/wash/retention/severity/settlement thresholds + deterministic operator ids `OP_METER`/`OP_SCALE`/`SO_1`/`SO_2` for SoD scenarios), `test_users.py` (shared constants for the 5 opaque roles + mandatory `make_driver_headers`/`make_customer_rep_headers` entity-backed builders), `fixtures.py` (tiered composite helpers: master-data primitives → `setup_draft/planned/loading/loaded_shipment` → `setup_in_transit/delivering/delivered/variance_review/reconciled_shipment` → `create_approved_spill_plan`, `create_certified_cert`, `create_active_agreement`).
- **`test_suite/`** — `conftest.py` + 11 test files, **102 test functions** total, organized by concern (baseline CRUD → RBAC → planning → loading/weights → departure → delivery/variance → billing → wash certs → incidents → dedicated program → OCC/retrieval).

**Coverage**
- **Queue A (Difficulty): 18/18 instances translated, each with ≥2 tests** (both a nominal and an adversarial/boundary angle per instance).
- **Queue B (Corner): 65/65 non-stub instances translated, each with ≥1 test.**
- **Instances skipped: 0** — every instance passed the PRD-first two-condition filter; the PRD (§2.5–2.9, §3.1–3.8) verbatim-covers and uniquely derives every asserted outcome, including the pinned validation pipeline (used by the two priority-pair instances), per-line rounding order, half-open window semantics, SoD rules, and lazy expiry.
- **5 corner stubs** (`abort_voids_meter_ticket`, `rack_window_conflict_error`, `wash_bay_window_conflict_error`, `cert_invalid_state_error`, `axle_limit_error`) not translated; all `difficulty_instance` cross-references verified to resolve to real queue-A instances.

**Tag audit** — all 102 tests carry exactly one `Design:` line; every tag resolves to an existing non-stub instance (no untagged, dual-tagged, or dangling tags). **PRD citation audit** — every quoted passage ≥30 chars survives a whitespace-normalized literal grep of PRD.md (18 initially-elided citations were rewritten to contiguous verbatim quotes). No `skip`/`skipif`/`xfail` markers; no scaffold/table references in generated comments. All files pass AST syntax checks, and every `from test_helpers import ...` name statically resolves against the helpers' exported namespace.

## Step 6: Generate Implementation — 2026-08-13T10:45:00.000Z

**Implementation complete** at `/home/ubuntu/github/CodingPRD/tasks/task_1446_tanker_bulk_liquid_trucking/workspace/implementation/` — Python 3 + Flask, in-memory dict storage, no seeding, empty store on every boot (verified: fresh boot returns `total_count: 0` and `created_at` of first entity reads the pinned logical clock `2026-08-01T00:00:00.000Z`).

### File list (line counts)
| File | Lines | Role |
|---|---|---|
| `start.sh` | 15 | Launcher (see contract below) |
| `requirements.txt` | 1 | `flask` |
| `app.py` | 55 | Flask app, ApiError/404/405/500 handlers, blueprint registration under `/bulk-liquid`, per-request store lock |
| `db.py` | 44 | Store: 15 entity dicts, logical clock (default 2026-08-01T00:00:00Z), insertion seq |
| `errors.py` | 121 | ApiError + all 64 catalog IDs → HTTP statuses + per-collection 404 map |
| `respond.py` | 35 | Envelope: `meta.api_request_id/api_request_timestamp`, `response_type`, `data`; error shape; pagination in meta |
| `authz.py` | 57 | X-User-ID/X-User-Role auth (400), role gating (403), Driver/CustomerRep entity-identity checks |
| `timeutil.py` | 91 | ISO datetime/date parsing, 3-fractional-digit `Z` formatting, month windows |
| `store_ops.py` | 194 | Field validators (str/int/number/bool/enum/list/datetime), unknown-field rejection, pagination, `touch` (version+updated_at) |
| `calc.py` | 210 | All 8 calculations in Decimal |
| `cascades.py` | 76 | Compensating releases, exposure recompute, lazy EXPIRED transitions |
| `serialize.py` | 263 | 15 entity serializers (exact scaffold field sets) |
| `routes/` (14 files) | 1,650 | clock 18, customers 80, products 60, compat_rules 64, trailers 73, drivers 76, wash_bays 47, wash_certs 165, racks 57, shipments 598, tickets 175, spill_plans 154, incidents 144, agreements 195, `__init__` 20 |

Total ~3,090 lines (`.deps_installed` is a 0-byte runtime sentinel created by start.sh).

### start.sh contract
Reads `$PORT` (default 10000), binds `0.0.0.0`, runs `exec python3 app.py` in the foreground. Dependency install is guarded (sentinel `.deps_installed` + `python3 -c "import flask"` check) so per-test reboots skip pip. Verified booting cleanly via `bash start.sh` on default and custom ports across multiple fresh processes.

### Coverage
- **77/77 endpoints** registered and exercised (clock, 15 resources, all actions; counted programmatically from the Flask url_map).
- **11 state machines**: Customer, Driver, TankTrailer (AVAILABLE⇄ASSIGNED), TankWashCertificate (incl. lazy CERTIFIED→EXPIRED on read, HELD→CONSUMED/ CERTIFIED compensations, revoke 2-hop cascade), Shipment (full DRAFT→…→RECONCILED chain incl. LOADING↔PLANNED cycle and VARIANCE_REVIEW branch), MeterTicket, DeliveryTicket (ACCEPTED/VARIANCE split on equality-accepts), RetainSample, SpillResponsePlan (incl. APPROVED⇄SUSPENDED, reinstate keeps expires_at, lazy EXPIRED), SpillIncident (REPORTED⇄UNDER_REVIEW, reopen SoD), DedicatedTrailerAgreement (PENDING→ACTIVE→SUSPENDED-by-threshold→TERMINATED).
- **8 calculations** implemented in `Decimal` with pinned rounding, verified against the design files' precomputed values: net60 (333 gal @85 °F → 327.2), billing per-line rounding (final 28014 ≠ sum-first 28013; provisional 535000 vs final 516106 divergence), allowed-loss cap (50.0 at 3000 mi; variance 15.0 == 15.0 accepts), axle compliance (equality passes at 34000, GVWR order, 3 % sum tolerance), wash ranks, credit exposure (25400 estimate → 26440 recompute; DRAFT/CANCELLED excluded), shortfall (floor ceil(0.8·5)=4, fee 100000, month ordering), spill severity tiers (9/10/100 boundaries, 12 h inclusive deadline).
- **Validation pipeline** ordered per PRD §2.8 (auth → authz/identity → existence → shape → OCC → state → safety → temporal → constraint → referential → fiscal), verified with the pinned priority tests: existence-beats-state (404 on cancelled-shipment plan with bogus trailer), state-beats-safety, safety-beats-fiscal (422 endorsement before 402 credit).
- **64/64 error codes** with exact catalog HTTP statuses; per-resource 404 IDs all verified.
- **7 roles** incl. entity-backed Driver/CustomerRep identity (403 on foreign ownership), both SoD rules (meter-closer ≠ weight-verifier; incident-closer ≠ reopener).
- **2 OCC rules** (`expected_shipment_version`, `expected_agreement_version`; required-int shape → 412 stale → 409 state; version +1 on success).

Verified by ~165 behavioral checks across 4 independent fresh-boot smoke runs; all pass (the only failures encountered were fixture bugs in my own ad-hoc scripts, not the implementation).

## Step 7: Run Tests and Iterate — 2026-08-13T10:58:00.000Z

All 8 rounds pass 102/102. Clean sweep achieved.

- **Iterations run:** 2 (initial sweep: 100/102 in all 8 rounds; post-fix sweep: 102/102 × 8 rounds, zero flakiness).

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1446_tanker_bulk_liquid_trucking/test_helpers/fixtures.py` — `record_weights()` fixture: the hard-coded default axle weights (6600/12500/12900 = 32000 lb) only satisfy the PRD §3.4 weight-sum-consistency check for the default 1000-gal @ 60°F load. Two tests (`test_billing_provisional_vs_final_divergence`, `test_billing_per_line_rounding_beats_sum_first`) drove the fixture chain with non-default loads (5000 gal @ 100°F → expected gross 59020 lb; 100.1 gal @ 60°F → expected gross 25701 lb), so the implementation's PRD-required `ERR_WEIGHT_SUM_INCONSISTENT` check correctly rejected the setup request. Changed the signature defaults to `None` and added `_compliant_weights()`, which fetches the shipment/trailer/product/closed meter ticket via the API and derives an axle distribution whose sum exactly equals the PRD §3.4 expected gross (tare + round-half-up(net60 × density)), each axle within its inclusive rating. Explicit-value call sites (all the test_04 compliance-failure tests) are unaffected.

- **Fixes applied to `implementation/`:** None — the implementation's `ERR_WEIGHT_SUM_INCONSISTENT` enforcement was PRD-faithful; the bug was entirely in the test fixture (STEP 2: fixture issued a request inconsistent with the preconditions it had constructed).

- **Diagnostic path:** STEP 0 found the identical setup failure (`record_weights → 422 ERR_WEIGHT_SUM_INCONSISTENT`) in both failing tests across all 8 rounds (deterministic, not flaky). STEP 1: PRD §3.4 verbatim-covers the expected-gross/3% rule and uniquely determines the rejection. STEP 2: test fixture constructed an inconsistent precondition → fixed the fixture, kept the implementation check intact.

## Step 8: Finalize PRD — 2026-08-13T11:02:00.000Z

**Conclusion: zero edits warranted.** The sole Step 7 item is a pure fixture bug, and `PRD_FINALIZED.md` has been written as a verbatim copy of `PRD.md` (diff-identical, 359 lines).

- **Line counts / %-delta:** `PRD.md` = 359 lines, `PRD_FINALIZED.md` = 359 lines, 0.0% delta (verbatim copy at `workspace/PRD_FINALIZED.md`).
- **Changes:** None — no insert or revise bullets.

**Why the single Step 7 item required no PRD edit**

The only fix was `test_helpers/fixtures.py` `record_weights()` — hard-coded default axle weights (6600/12500/12900) were replaced by `_compliant_weights()`, which derives a compliant axle distribution from live API data. Every behavior this fixture fix touches is already uniquely pinned by the PRD and matched verbatim by the implementation:

- PRD §3.4 (line 164) fully specifies the weight-verification gate: pinned check order (steer → drive → trailer → GVWR → sum-consistency), inclusive axle ratings, expected gross = `tare_weight_lb` + round-half-up(`net60_gallons` × `density_lb_per_gal`), 3% inclusive tolerance, `ERR_WEIGHT_SUM_INCONSISTENT`. The implementation matches exactly: `implementation/routes/shipments.py:440-480`, `implementation/calc.py:112-117` (`product_weight_lb`, `expected_gross_lb`), `implementation/calc.py:22` (`WEIGHT_SUM_TOLERANCE_PCT = Decimal("0.03")`, with `>` comparison making the boundary inclusive as the PRD states).
- The per-axle tare fields the fixture reads (`tare_steer_lb`/`tare_drive_lb`/`tare_trailer_lb`) are already documented in PRD §2 (line 118) with the exact sum-equals-tare constraint (`ERR_TARE_AXLE_MISMATCH`), matching `implementation/routes/trailers.py:16,29-32` and `implementation/serialize.py:67-70`.
- The Step 7 diff itself confirms the implementation's check was "PRD-required" and "correctly rejected the setup request" — the fixture's static data was simply invalid for non-default loads. No implementation fix, no test deletions, no PRD silence revealed.

**Per-edit pre-edit search log (mandatory even for zero-edit outcome)**

For the one candidate edit subject considered:

- (a) **Subject:** weight verification / expected-gross formula and weight-sum-consistency check (PRD §3.4).
- (b) **Impl paths enumerated and read:** `implementation/routes/shipments.py:440-480` (`record_weights` endpoint — state gates, once-only check, axle checks, GVWR, sum-consistency, segregation-of-duties); `implementation/calc.py:109-117` (`product_weight_lb`, `expected_gross_lb`) and `calc.py:22` (tolerance constant); `implementation/routes/trailers.py:16,29-32` (tare decomposition validation); `implementation/serialize.py:67-70` (trailer tare fields exposed to the fixture); `test_helpers/fixtures.py:180-221` (`record_weights` + `_compliant_weights`); plus a grep of `PRD.md` for `tare`/`WEIGHT_SUM`/`3.4` (lines 97, 118, 164, 339) confirming full existing coverage.
- (c) **Wording adjustment:** None — every enumerated path is already accurately and completely described by the existing PRD prose, so no edit was committed and no consistency risk arose.

## Step 9: Complete PRD — 2026-08-13T11:22:00.000Z

PRD_COMPLETED.md is complete. All edits verified via diff — only the intended paragraphs changed.

**Source vs output:** `PRD_FINALIZED.md` (359 lines, 58,399 chars) → `PRD_COMPLETED.md` (362 lines, 62,125 chars; **+3 lines, +3,726 chars**).

**Counts:** 14 ambiguity-pins, 3 mismatch-revisions (17 edit sites total).

**Changes:**

- §2.2 — insert — ambiguity — pinned `api_request_timestamp` as wall-clock receipt time, not the logical clock — `implementation/respond.py:13` vs `db.py:12`.
- §2.2 — insert — ambiguity — pinned the primary-resource rule for multi-resource actions: check-in/abort-loading/start-delivery return the shipment, close-meter returns the closed MeterTicket, delivery close returns the closed DeliveryTicket — `routes/shipments.py:371,387,437,551`, `routes/tickets.py:136`.
- §2.2 — insert — ambiguity — pinned unmatched route → `ERR_NOT_FOUND` (404), unsupported method on a defined path → `ERR_NOT_FOUND` (405) — `app.py:33-39`.
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; out-of-range integers clamped (`limit` into [1,100], `offset` floored at 0); `has_more` = offset + returned < total_count; `created_at` ties broken by insertion order — `store_ops.py:163-194`.
- §2.4 — revise — ambiguity — pinned `version` starts at 1 on creation — `store_ops.py:17-19`.
- §2.5 — revise — ambiguity — clock-set accepts any ISO 8601 instant (no monotonicity enforced; backward allowed), returns 200 with empty `data` — `routes/clock.py:12-18`.
- §2.7 — revise — ambiguity — a revision with matching expected version but no field changes still succeeds and increments `version` — `routes/shipments.py:128-145`, `routes/agreements.py:104-118`.
- §2.8 step 2 — revise — ambiguity — pinned identity-vs-existence ordering: role membership before any lookup; body-value identity checks (shipment/plan creation) before body-reference existence; resource-dependent identity checks (start-delivery, delivery close, cancel, submit, incident report) evaluated right after the resource loads, so an unknown path id yields 404 even when identity would mismatch — `routes/shipments.py:51-52,311-312,526-528`, `routes/tickets.py:74-79`, `routes/incidents.py:29-33`, `routes/spill_plans.py:93-95`.
- §2.8 step 4 — revise — ambiguity — meter readings and recorded axle weights may be zero (>= 0); ordered gallons, route miles, rates, delivered/spilled gallonage, retain-sample ml strictly positive — `routes/shipments.py:397-398,446-448`, `routes/tickets.py:83-85`.
- §3.1 — revise — mismatch — dropped uniqueness claims for `bay_code` and `rack_code`; impl enforces neither (only unit_number, cdl_number, compatibility pairs) — `routes/wash_bays.py:18-32`, `routes/racks.py:18-42`.
- §3.2 — insert — ambiguity — booking does not validate `wash_level` against the bay's `supported_wash_levels` (descriptive only) — `routes/wash_certs.py:26-71` (no such check).
- §3.3 — revise — ambiguity — omitting a mandatory certificate fails with `ERR_CERT_INVALID_STATE`; a certificate issued for a different trailer is rejected with `ERR_CERT_INVALID_STATE` regardless of requirement (even when `NONE`) — `routes/shipments.py:185-200`.
- §3.4 — revise — mismatch — the SoD check in record-weights runs after all axle/weight checks (§2.8 category 7 before category 9), so a request violating both draws the axle error; PRD prose had implied SoD first — `routes/shipments.py:455-476`.
- §3.4 — insert — ambiguity — placard confirmation may be repeated while `LOADED`, each success re-mutating the shipment — `routes/shipments.py:482-497`.
- §3.6 — revise — mismatch — exposure is recomputed at six moments, adding the held-certificate revocation cascade (PRD said five and omitted it) — `routes/wash_certs.py:151`.
- §3.7 — revise — ambiguity — the reject `reason` is accepted but not stored on the plan — `routes/spill_plans.py:118-128`.
- §3.8 — revise — ambiguity — `effective_from`/`effective_to` are ISO 8601 datetimes (bare date = midnight UTC, serialized as full timestamps); the period-overlap check runs before the enrollment check — `routes/agreements.py:39-54`.
- §4 — revise — ambiguity — side-effect-only resource creation (check-in/start-delivery/delivery close) returns 200, not 201 — `routes/shipments.py:371,551`, `routes/tickets.py:136`.
- §5 — insert — ambiguity — added `ERR_NOT_FOUND` catalogue row (404; 405 when path exists but method unsupported) — `app.py:33-39`, `errors.py` (handler-level id outside the 64-id catalog).

**Verification:** all endpoints, state transitions, formulas, validation ordering, defaults, and response shapes in `implementation/` (app.py, authz.py, calc.py, cascades.py, db.py, errors.py, respond.py, serialize.py, store_ops.py, timeutil.py, and all 15 route modules) were walked; every other impl behavior was already uniquely pinned by PRD prose. All 8 recorded test runs show 102/102 passing; tests were used only as cross-reference.
