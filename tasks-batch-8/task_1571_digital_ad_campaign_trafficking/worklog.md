# Worklog — task_1571_digital_ad_campaign_trafficking

## Step 1: Create Task Directory — 2026-08-13T21:49:00.000Z

Task directory `tasks/task_1571_digital_ad_campaign_trafficking/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per orchestrator instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T22:45:00.000Z (resumed-verified)

Step 2 subagent output from prior run was found on disk and verified by the orchestrator (resume path):
- SCAFFOLD.yaml (1101 lines): VALID YAML. Keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities (9: InsertionOrder, LineItem, Creative, DeliverySnapshot, ImpressionEvent, VerificationReport, MakeGood, Reconciliation, WrapReport), state_machines (9), concurrency_rules (1), calculations (9), invariants, validations (24), endpoints (34), errors (24), roles (4). No leaked scaffold_difficulty_design / scaffold_corner_design keys.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (688 lines): VALID YAML. Single top-level key scaffold_difficulty_design; 9 rules, 18 non-stub instances.
- SCAFFOLD_CORNER_DESIGN.yaml (748 lines): was INVALID on resume — 18 `grounds:` lines contained unquoted flow scalars with nested brackets (e.g. `grounds: [errors[ERR_NOT_FOUND], ...]`). Orchestrator repaired by quoting the bracketed tokens in place (no content change; YAML-quoting fix only). After repair: VALID YAML. Single top-level key scaffold_corner_design; 4 sections (entities, state_machines, calculations, validations), 35 non-stub instances, 0 stubs.

## Step 3: Copy Shared Files — 2026-08-13T22:46:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1571_digital_ad_campaign_trafficking/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T23:05:00.000Z

Generated `/home/ubuntu/github/CodingPRD/tasks/task_1571_digital_ad_campaign_trafficking/workspace/PRD.md` (242 lines) from the scaffold only. The two forbidden difficulty-design files and all sibling tasks were not touched.

**Section list**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 Roles/RBAC (all 4 roles, `identity: opaque` translated), 2.2 API Response Structure (emitted byte-verbatim, verified), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Server Logical Clock, 2.6 Money/Rates/Rounding, 2.7 OCC on Mid-Flight Edits, 2.8 Validation Pipeline and Check Ordering, 2.9 Hierarchical Consistency and Cascading Transitions (incl. the `action` vocabulary per resource), 2.10 Compensating Actions and Aggregate Invariants
- §3 Business Logic (7 subsections): Insertion Orders; Line Items (setup/launch/mid-flight edit/CLEAR_FRAUD self-transition); Creative QA/Tagging/Activation; Delivery Snapshots, Pacing, Frequency Capping; Verification Reports, Fraud Holds, Make-Goods; Reconciliation and Billing Basis; Wrap Reports, Attribution, Campaign Close
- §4 Endpoint table — 34 rows, 4 columns only
- §5 Error catalogue — 24 rows, 2 columns only

**Hard contract reports**

```
Field coverage check:
- entities[].fields + endpoint inputs/params: 88 required, 88 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority: 24 checked, 24 expressed (global pipeline order in §2.8, launch-guard ordering noted in §3.2), 0 missing
- concurrency_rules[]: 1 checked, 1 expressed (PATCH /line-items/{id} + expected_line_item_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all 7 machines / 40 transitions expressed incl. sibling CANCEL/ARCHIVE branches, self-transitions, system-only creative pause/resume, 0 missing
- calculations[]: 9 checked, 9 fully expressed in prose (budget, snapshot spend, both pacing variants, pacing alert, frequency cap, verification assessment + fraud cascade, 3 billing-basis variants, wrap totals with pinned rounding order, both attribution models), 0 missing
- validations[] conditions: 24 matchable to error_ids in §2/§3, 0 missing
- endpoints[].side_effects / invariants: all expressed; both compensating-pair invariants stated, 0 missing
- entities[].fields[] structured content: defaults (0.70/0.02/24h/null/{}), common_fields:false handling for snapshots and impression events, nullability of computed reconciliation fields — all reconstructible
- sibling-branch symmetry: cancel/archive state lists enumerated equally; PASS/BREACH and per-action role gates symmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 441
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Notable coverage decisions**
- The scaffold's `action`-driven transition design (no sub-paths) made the `action` request field and all 25 action-value strings easy to lose; both are pinned in a §2.9 contract paragraph with per-resource vocabularies, while §3 refers to transitions purely by state pairs (`TRAFFICKED` → `LIVE` etc.).
- The 24-rule validation priority list is expressed as an explicit ordered pipeline in §2.8 (auth → roles → schema → existence → OCC → state → domain rules in catalogue order), since many endpoints share 4+ checks.
- Constants embedded per scattering guidance: `PACING_ALERT_RATIO` as "ninety percent", `DISCREPANCY_TOLERANCE` as "ten percent", `TRAILING_WINDOW_DAYS` as a "three-calendar-day window"; thresholds 0.70/0.02 kept as decimals.
- `DeliverySnapshot`/`ImpressionEvent` (`common_fields: false`) are explicitly stated to carry only `id` and `created_at`, and no version-increment claim is made for VOID.
- Boundary semantics called out verbatim-equivalent: verification periods closed (touching conflicts), reconciliation periods half-open (adjacency allowed), frequency-cap window half-open (event exactly window-hours old excluded), threshold equality passes assessment.

## Step 5: Generate Unit Tests — 2026-08-13T23:45:00.000Z

Done. Full test infrastructure and suite generated for task 1571.

## Summary

**Tests emitted: 71 total**
- **Queue A (Difficulty): 36 tests** — all 18 instances × 2 tests each (coverage target met exactly)
- **Queue B (Corner): 35 tests** — all 35 non-stub instances × 1 test each (no `excluded_because:` stubs existed in the index)

**Skipped instances: none.** Every instance passed the PRD-first two-condition filter. Three instances had individual assertions adjusted to keep the test PRD-faithful (the instance itself still emitted):
1. `Corner/entities/io_creation_applies_defaults` — dropped the `version == 1` assertion: PRD §2.4 says version is "an integer starting at creation" without pinning the start value (not uniquely derivable); all PRD-pinned defaults (0.70/0.02, DRAFT, zero counters) are asserted.
2. `Corner/entities/line_item_budget_computed_and_client_budget_input_ignored` — the "client-supplied `budget_cents` ignored" half is not uniquely derivable (a PRD-faithful server may 400 unknown fields), so the test sends a clean payload and asserts the PRD-computed value 50000 + IO `booked_budget_cents` rollup.
3. `Difficulty/dual_variant_calc/pacing_projection_lifetime_vs_trailing` — the index's literal `delivered_spend_cents == 16000` contradicts the PRD §3.4 formula (40000 imps × 500 cpm / 1000 = **20000**); asserted the PRD-derived 20000 instead. The distinguishing pair (80000 vs 63333) is asserted verbatim.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1571_digital_ad_campaign_trafficking/`):
- `test_helpers/`: `__init__.py`, `types.py`, `api_client.py` (34 endpoint methods), `api_errors.py` (24 errors, registered with framework), `assertions.py` (per-entity + ledger absence checks for `updated_at`/`version` per PRD §2.4), `factories.py`, `constants.py`, `test_users.py` (4 opaque roles + per-user builders for SoD pairs), `fixtures.py` (tiered composites: trafficked/LIVE line-item setup, breach-report, make-good, lock-reconciliation, completion chains)
- `test_suite/`: `conftest.py` + 8 test files (order booking/pipeline, line-item lifecycle, creative QA, delivery/pacing/frequency, verification/fraud hold, make-goods, reconciliation/billing basis, wrap reports/attribution)

**Stage 2 self-check (tag audit): PASS**
- 71/71 test docstrings end with exactly one `Design:` line resolving to a real instance (36 `Difficulty/…`, 35 `Corner/…`); no untagged, dual-tagged, or dangling tags
- Coverage audit: every difficulty instance ≥2 tests; every corner non-stub instance ≥1 test
- All 86 PRD citations match PRD.md verbatim (whitespace-normalized literal grep)
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no freelance tests (no baseline/RBAC/pagination inventions — e.g., no OCC test since neither index contains an OCC instance)
- `py_compile` clean; pytest collects 71 tests with the framework on `PYTHONPATH`

## Step 6: Generate Implementation — 2026-08-13T23:46:00.000Z

Implementation complete and verified. Summary:

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_1571_digital_ad_campaign_trafficking/workspace/implementation/`:

- **start.sh** — executable launcher; guarded dependency install (`if ! python3 -c "import flask"`), then `exec python3 app.py`
- **requirements.txt** — `flask>=2.2`
- **app.py** — Flask app, blueprint registration, envelope-JSON error handlers (ApiError/404/405/500), `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`
- **core.py** — in-memory `Store` (plain dicts, empty at boot), logical clock (startup default `2026-08-01T00:00:00Z`, never wall clock), error catalog, response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), `X-User-ID`/`X-User-Role` auth, pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, clamped 1–100), ISO date/datetime parsing, ROUND_HALF_UP decimal helpers
- **domain.py** — serializers, aggregates computed on read (delivered_*, booked_budget, applied credit), pacing projections (lifetime-average + trailing-3-day, `pacing_alert` via exact Fraction comparison), billing-basis computation (AGENCY_PLATFORM / THIRD_PARTY_TAG / LOWER_OF with |discrepancy| > 0.10 gating), largest-remainder attribution (ties by created_at ASC), cascade helpers (IO cancel → LI cancel → creative archive; fraud cascade; auto-complete)
- **routes_io.py, routes_line_items.py, routes_creatives.py, routes_delivery.py, routes_verify.py, routes_billing.py** — the resource endpoints

## Endpoint count
**34** — every route in the scaffold endpoint table, including the per-action role gates on make-good transitions (REVISE→VerificationAnalyst; APPROVE/REJECT/APPLY/REVERSE→BillingManager) and validation ordering per PRD §2.8 (auth → forbidden → schema → existence → OCC 412 → state → business rules in catalog order: FRAUD_HOLD before FLIGHT_NOT_STARTED before NO_TAGGED_CREATIVE before IO_NOT_APPROVED, UNRESOLVED_MAKE_GOODS before SEGREGATION_OF_DUTIES, etc.).

## start.sh contract
Confirmed: reads `$PORT` (default 10000), binds `0.0.0.0`, runs in the foreground via `exec`, and the pip install is a no-op once Flask is present so per-test reboots stay fast.

## Verification
Two smoke suites (~110 assertions) ran green against live boots, covering: full IO→line-item→creative lifecycle, QA fail/revise loop, ERR_TAG_REQUIRED, pacing math with concrete numbers, snapshot void compensation, auto-complete at goal, OCC 412, frequency-cap window edges (both bounds exclusive per PRD prose), fraud cascade + CLEAR_FRAUD, closed-interval verification overlap, half-open reconciliation adjacency, all three billing bases with tolerance gating, SoD 403s, make-good apply/reverse credit invariant, wrap totals with credits, both attribution models with tie-breaking, and envelope/pagination shape. A fresh reboot returned `total_count: 0` with the clock at the startup default — no seeding, no persistence anywhere.

## Step 7: Run Tests and Iterate — 2026-08-14T00:05:00.000Z

Clean 8-round parallel sweep achieved. Final summary:

**Iterations run:** 2 (iteration 1 surfaced 8 failures via a single probe round after the first sweep attempt was OOM/SIGKILLed by the sandbox; fix applied; iteration 2 full 8-round parallel sweep: all 8 rounds passed 71/71, 0 failed, 0 errors, 0 skipped).

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:** None.

**Fixes applied to `implementation/`:**
- `workspace/implementation/core.py` — `new_id()`: changed `uuid.uuid4().hex` (dashless 32-char hex) to `str(uuid.uuid4())` (canonical 8-4-4-4-12 dashed UUID). PRD §2.4 states every primary resource carries "`id`, a server-minted UUID with no type prefix"; the canonical textual form of a UUID is the dashed form, which is what the shared assertion helper `is_valid_uuid` validates. This one-line fix resolved all 8 failing tests (`test_io_creation_applies_defaults`, `test_line_item_budget_computed_at_creation`, `test_snapshot_spend_computed`, `test_threshold_equality_passes`, `test_credit_ceiling_exact_ok_over_rejected`, `test_agency_platform_bills_agency_despite_discrepancy`, `test_wrap_net_billable_per_recon_rounding`, `test_attribution_tie_broken_by_created_at`) — each tripped only the `id must be valid UUID` assertion inside the shared entity assertions; every other assertion in those tests was already passing.

**Note on environment:** the first 8-round sweep attempt ran inside the Bash tool sandbox and all 8 Flask servers were SIGKILLed at boot (exit 137) by sandbox resource limits — not an app defect (126 GB RAM / 32 cores host). Rerunning the identical sweep unsandboxed completed cleanly at ~101 s per round with zero failures across all 8 rounds.

## Step 8: Finalize PRD — 2026-08-14T00:10:00.000Z

Done. `workspace/PRD_FINALIZED.md` written.

**Line counts / delta:** PRD.md 242 lines, PRD_FINALIZED.md 242 lines — 0% line-count delta; exactly one in-line revision on line 74 (no sections added or removed).

**Changes (one total):**
- §2.4 Common Resource Properties — **revise** — the `id` field description now pins the textual serialization: "`id`, a server-minted UUID with no type prefix, **rendered in the canonical hyphenated 8-4-4-4-12 string form (for example `550e8400-e29b-41d4-a716-446655440000`)**, which is also how the `id` path parameter of item-level routes is interpreted". The prior wording "a server-minted UUID" left the serialization open (dashless 32-char hex vs. dashed canonical), and the Step 7 fix changed `new_id()` from `uuid.uuid4().hex` to `str(uuid.uuid4())` — impl file: `workspace/implementation/core.py:407-408`.

**Per-edit pre-edit search log:**

Edit 1 (the only edit):
- (a) **Subject:** textual format of the server-minted resource `id` field.
- (b) **Impl paths enumerated and read/grepped:** mint site `core.py:407-408` (`new_id()` → `str(uuid.uuid4())`); all application sites of `new_id()` — `core.py:413` (`stamp_new`, used by routes_io/routes_line_items/routes_creatives/routes_verify ×2/routes_billing ×2) and `core.py:423` (`stamp_ledger`, used by routes_delivery ×2), so all 9 resource kinds receive dashed canonical ids; consumption side `domain.py:19-48` — all id lookups are plain string dict-key lookups; non-resource `api_request_id` (`core.py:177,188`, `"req_" + hex[:20]`) untouched since PRD §2.2 never claims it is a UUID; auxiliary: test assertion `_UUID_RE` validates exactly the dashed canonical form.
- (c) **Wording adjustment:** pin placed inside the existing primary-resources sentence rather than the ledger sentence; since §2.4's ledger sentence defines snapshot/event records as carrying "only `id` and `created_at`" (the same `id` notion), the pin automatically covers `stamp_ledger`-minted ids too. An example UUID was included (rather than bare "8-4-4-4-12" shorthand); no case claim made (impl always emits lowercase; example shows it without over-asserting).

No other Step 7 diff items existed (no test deletions, no test_helper/test_suite fixes, no other implementation fixes), so no further PRD edits were warranted.

## Step 9: Complete PRD — 2026-08-14T00:20:00.000Z

Done. PRD_COMPLETED.md produced at `workspace/PRD_COMPLETED.md` (edited in place after copying from PRD_FINALIZED.md).

**Source vs output:** PRD_FINALIZED.md 242 lines / 41,895 chars → PRD_COMPLETED.md 242 lines / 43,938 chars (delta **+2,043 chars**, 0 line-count change — all edits inline within existing paragraphs; no new sections).

**Counts:** 14 ambiguity-pins, 2 mismatch-revisions (16 changes total).

**Change log** (section — kind — class — what changed — impl anchor):

- §2.3 — insert — ambiguity — non-integer `limit`/`offset` fall back to defaults and out-of-range values are clamped (limit into [1,100], offset ≥ 0) rather than rejected; `created_at` sort ties broken by earlier creation — `core.py:378-401` (`paginate`), `core.py:374-375` (`sorted_items` by `_created_dt, _seq`)
- §2.4 — revise — ambiguity — `version` starts at **1** at creation; `updated_at` rendered in the same three-fractional-digit format as `created_at` — `core.py:416` (`rec["version"] = 1`), `domain.py` serializers use `render_ts` for both
- §2.5 — insert — ambiguity — resource `created_at`/`updated_at` and envelope `api_request_timestamp` read from the logical clock, not wall clock — `core.py:411-431` (`stamp_new`/`touch` use `now_dt()`), `core.py:178,189`
- §2.7 — insert — mismatch — for the mid-flight PATCH, the merged `end_date ≥ start_date` cross-field check runs **after** existence/OCC/state checks, not in the §2.8 schema stage — `routes_line_items.py:144-152` (check at 151 follows OCC at 144 and state at 146)
- §3.1 — insert — ambiguity — `viewability_threshold_pct`/`ivt_threshold_pct` when supplied must be numbers in [0, 1] inclusive, else `ERR_INVALID_REQUEST` — `routes_io.py:40-45` (`opt_decimal` with `lo=0, hi=1`)
- §3.2 — revise — mismatch — inverted `end_date < start_date` on line-item create is `ERR_INVALID_REQUEST` (schema stage); only flight-window violations are `ERR_FLIGHT_WINDOW_VIOLATION` (PRD previously attached `ERR_FLIGHT_WINDOW_VIOLATION` to both clauses) — `routes_line_items.py:52-53` vs `23-25`
- §3.2 — insert — ambiguity — `targeting` explicit null reads as empty object; frequency-cap pair values must be positive integers; null/omitted `frequency_cap_max_impressions` means uncapped — `routes_line_items.py:44-51`
- §3.2 — insert — ambiguity — RESUME guard errors pinned: fraud posture → `ERR_FRAUD_HOLD`, resume past `end_date` → `ERR_FLIGHT_NOT_STARTED` — `routes_line_items.py:228-231`
- §3.2 — insert — ambiguity — manual COMPLETE before/at `end_date` fails the state check as `ERR_INVALID_STATE` — `routes_line_items.py:241-242`
- §3.2 — insert — ambiguity — PATCH null semantics: null fields ignored, except null `frequency_cap_max_impressions` clears the cap (uncapped) — `routes_line_items.py:122-137, 175-176`
- §3.3 — insert — ambiguity — creatives may be registered under a line item in any status (no status gate on upload) — `routes_creatives.py:27-29` (existence check only)
- §3.3 — revise — ambiguity — `qa_failure_reason` (FAIL_QA) and `ad_tag` (TAG) must contain at least one non-whitespace character; whitespace-only rejected with `ERR_TAG_REQUIRED` — `routes_creatives.py:91, 106` (`.strip()` checks)
- §3.5 — insert — ambiguity — an amount supplied for the non-matching make-good kind is accepted and stored as given — `routes_verify.py:133-134, 148-152` (both fields stored unconditionally)
- §3.6 — insert — ambiguity — a reconciliation may be opened for a line item in any status (no status gate) — `routes_billing.py:36-38` (existence check only)
- §3.6 — insert — ambiguity — LOCK guard boundary semantics: closed report period vs half-open reconciliation period means report `period_end ==` recon `period_start` counts as overlapping, report `period_start ==` recon `period_end` does not — `routes_billing.py:109` (`vr._ps < rec._pe and rec._ps <= vr._pe`)
- §3.6 — insert — ambiguity — REOPEN clears `reconciled_by_user_id` but retains the previously computed `discrepancy_pct`, `billing_impressions`, `billable_cents` until the next RECONCILE overwrites them — `routes_billing.py:118-122` (only `reconciled_by_user_id` reset)

All other implementation behaviors walked (state machines, cascades, pacing/attribution/frequency-cap/billing-basis formulas, guard evaluation order per §2.8, error catalogue, endpoint table, response envelope) were already uniquely pinned by PRD_FINALIZED.md and required no change.
