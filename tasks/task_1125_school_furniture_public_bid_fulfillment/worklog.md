# Worklog — task_1125_school_furniture_public_bid_fulfillment

## Step 1: Create Task Directory — 2026-08-10T20:04:00.000Z

Pre-assigned output folder `tasks/task_1125_school_furniture_public_bid_fulfillment` with `workspace/` subdirectory already exists; Step 1 auto-index scan skipped per instructions. Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-10T20:39:00.000Z

All three scaffold artifacts are generated, parse cleanly, and pass `scaffold_lint.py` with a clean verdict on the first full run.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1125_school_furniture_public_bid_fulfillment/SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1125_school_furniture_public_bid_fulfillment/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1125_school_furniture_public_bid_fulfillment/SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

No sibling task directories were read; the design was derived purely from the scenario text plus the skill spec.

## Design summary (harder-than-expert calibration)

- **Archetype**: compliance/audit (public procurement: no-substitution rule, award spec-version pinning) × temporal windowing (summer delivery window, replacement deadlines, warranty terms); layers: optimistic concurrency, cascading side effects, version-pinning on approval, rate/threshold triggers. Flat topology, cyclic state-machine family, peer roles with entity-backed ownership (DistrictBuyer→District, CrewLead→Crew).
- **Entities: 14** — District, SchoolSite, BidSpec, SpecLine, CoopPriceAgreement, Award, PurchaseOrder, POLine, Shipment (absorbs replacement orders via `kind`), Crew, InstallTask, DamageReport, BackorderNotice, WarrantyClaim.
- **State machines: 9** — cyclic BidSpec addendum loop, WarrantyClaim appeal loop, BackorderNotice ETA loop, PO posture dimension; branching DamageReport; guarded cross-entity transitions (PO→Award, WarrantyClaim→POLine, InstallTask→Shipment).
- **Endpoints: 62** (includes 11 filtered-list GETs required for FK reverse-reachability and the `/_clock/set_current_utc` test-driving endpoint with the mandated 2026-05-01 default).
- **Error catalog: 29**; **calculations: 9** (2 dual-variant pairs: coop-tiered vs flat POLine pricing, standard vs extended-prorated warranty coverage; 2 combinatorial modes: marginal tier straddle + pinned per-line-round-then-sum closeout); **validations: 17** priority-ordered; **roles: 6**; **OCC concurrency rules: 2** (award amendment, backorder-notice supersede).

## Test targeting

- **Difficulty design: 18 instances** (all 9 rules × 2, each with falsifiable distinguishing aspects and pre-computed literal asserts — e.g., tier straddle total 223500, closeout 97600, prorated coverage 30000, deadline min-branch dates).
- **Corner design: 41 instances** (36 active + 5 `excluded_because` stubs) across all nine claim-extraction-guide sections, including both OCC 412 paths, no-substitution rejection, window-bound inclusivity, and immediate-consistency read-after-write.

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(62 endpoints, 14 entities, 18 §1.8 + 36 §1.9 active instances, 826 calls scanned.) Additional self-checks passed: key-file split honored, zero forbidden race vocabulary, all 59 instance names unique across both design files, every error code referenced at least once outside the catalog.

One fix applied during authoring: a marginal-tier arithmetic slip in the §1.8 straddle instance (corrected 225000 → 223500, unit 11175) and two unreachable/over-defensive error entries (`ERR_LINES_NOT_VERIFIED`) removed to keep every catalog error triggerable.

## Step 3: Copy Shared Files — 2026-08-10T20:40:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1125_school_furniture_public_bid_fulfillment/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T20:46:00.000Z

PRD generated and verified at `/home/ubuntu/github/CodingPRD/tasks/task_1125_school_furniture_public_bid_fulfillment/workspace/PRD.md`.

**Line count:** 323 lines.

**Sections:** §1 Introduction (2 paragraphs, business-context angle); §2 Global Specifications with 10 subsections (2.1 RBAC, 2.2 Response Structure verbatim, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Logical Clock, 2.6 Monetary Precision, 2.7 OCC, 2.8 Request Evaluation Order, 2.9 Procurement Integrity, 2.10 Conserved Quantities); §3 Business Logic with 9 lifecycle-grouped subsections; §4 Endpoint Definitions (62-row table, 4 columns); §5 Error Code Catalogue (29-row table, 2 columns).

**Coverage notes:**
- **Entities:** all 14 covered (District, SchoolSite, BidSpec, SpecLine, CoopPriceAgreement, Award, PurchaseOrder, POLine, Shipment, Crew, InstallTask, DamageReport, BackorderNotice, WarrantyClaim), every field name backticked.
- **State machines:** all 9 fully rendered — every transition's from/to states, preconditions paired with error IDs, and all side-effect cascades (including the three-link damage-replacement cascade, the three-link backorder cascade, and the completion bubble-ups).
- **Calculations:** all 9 expressed in precise prose (coop tiered marginal pricing with chronological volume base, flat variant, whole-dollar pinned-order closeout with 3% early-completion credit, warranty proration with 365-day started-year rounding, replacement deadline as min of window+14d and report+21d, drawdown/booking conservation invariants, half-open site capacity, posture threshold of 2).
- **Validations:** all 17 priorities expressed as an explicit evaluation pipeline in §2.8 plus per-endpoint orderings in §3 (e.g., the four ordered gates on PO line creation).
- **Endpoints:** all 62 in the §4 table with correct roles; request-body-only params (`to_iso8601`, `addendum_note`, `amendment_note`, `cancel_reason`, `initial_eta_date`, `note`, `new_eta_date`, `appeal_note`, `uncrated`, `debris_removed`, `placed`, `expected_award_version`, `expected_po_line_version`) all present in narrative.
- **Errors:** all 29 IDs mentioned in §2/§3 prose near their trigger workflows.
- **Roles:** all 6 with identity translations (DistrictBuyer/CrewLead entity-backed, four opaque roles).

**Hard contract reports:**
```
Field coverage check:
- entities[].fields + endpoint inputs/query/path: 94 required, 94 present, 0 missing
Status: PASS

Rule coverage check:
- validation priority ordering: expressed (global pipeline + per-endpoint gates), 0 missing
- concurrency_rules OCC: 2/2 expressed (write capability + expected field + ERR_STALE_VERSION/412)
- state machine transitions: all fully expressed incl. sibling branches (addendum loop, ETA loop, appeal loop, cancel branches)
- calculations: 9/9 fully expressed, constants embedded, no pseudocode/fuzzy words
- side effects / applies_to scopes: expressed (incl. posture-gate exemption, cascade-created task capacity checks)
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 523
- tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path combos: 0
Status: PASS
```

§2.2 verified byte-identical to the canonical block. The withheld difficulty/corner design files were not read.

## Step 5: Generate Unit Tests — 2026-08-10T21:04:00.000Z

Generation complete. Summary:

**Helper files written** (all 9, under `.../task_1125_school_furniture_public_bid_fulfillment/test_helpers/`):
- `types.py` — 14 entity TypedDicts (all `common_fields: true`), 12 status/kind enums, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with 62 methods, one per PRD §4 endpoint; `api_client` singleton
- `api_errors.py` — `ApiErrorId` (29 errors) + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + drawdown/booking invariant checkers
- `factories.py` — 13 payload factories, input fields only
- `constants.py` — clock default, windows, tier tables, closeout/replacement/posture constants
- `test_users.py` — `TEST_USERS` for 4 opaque roles + entity-backed builders `make_district_buyer_headers` / `make_crew_lead_headers`
- `fixtures.py` — tiered composites: primitives (clock/district/site/crew/coop/spec/award/PO/line/shipment/task), `build_awarded_context`, `build_accepted_award_context`, `add_accepted_po`, `ship_and_deliver`, `install_and_complete`, `build_verified_line_context`
- `__init__.py` — barrel export (framework + PRD-specific)

**Test files written** (`test_suite/`): `conftest.py` + 10 test files — bid-spec lifecycle, awards/PO intake, PO-line pricing, drawdown/closeout, shipments/delivery, install tasks/crews/sites, backorders, damage/replacement, warranty, validation-order/security.

**Test counts**: 72 tests total, 72 `Design:` tags (exactly one per test, verified 1:1).
- **Queue A (Difficulty)**: 18/18 instances translated, 36 tests (exactly ≥2 per instance).
- **Queue B (Corner)**: 36/36 non-stub instances translated, 36 tests (≥1 each).
- **Skipped instances**: 5, all `excluded_because:` stubs (never translated per spec), cross-references verified resolving: `po_closeout_total_cents_computed_at_close` → install_closeout instance; `error_po_at_risk_blocks_scheduling` → backorder cascade instance; `error_order_window_closed` → poline temporal-priority instance; `error_invalid_state_on_cancelled_po_accept` → po-accept priority instance; `error_warranty_expired` → warranty boundary instance.
- **Non-stub instances skipped on PRD-first grounds**: 0 — every instance had verbatim PRD coverage with a uniquely-derived outcome.

**Verification results**:
- `python -m py_compile` over all 20 files: **SYNTAX OK**.
- `import test_helpers` against the installed framework: **OK** (66 client methods).
- Automated tag audit vs both YAMLs: all difficulty tags at 2/2, all corner tags ≥1, zero unknown tags, zero stub translations: **PASS**.
- Verbatim citation sweep: 109 quoted PRD citations, every one has a ≥8-word window surviving literal grep of `PRD.md`: **PASS** (one C3 ellipsis abbreviation found and fixed with the full sentence).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere: confirmed 0 matches.

One judgment call to note: the warranty divergence instance's "400 days past base_end" is arithmetically 401 days across the 2032 leap year; the asserted outcome (`coverage_cents == 30000` via `ceil(days/365) = 2`) is identical either way, so the test is robust to the discrepancy.

Orchestrator disk verification: 9 test_helpers files + conftest.py + 10 test files present; 72 `def test_` counted; py_compile SYNTAX-OK over helpers, suite, and implementation.

## Step 6: Generate Implementation — 2026-08-10T21:04:00.000Z

Implementation complete. Summary:

**Files written** (27 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1125_school_furniture_public_bid_fulfillment/workspace/implementation/`):
- `start.sh` (guarded pip install, `exec python3 app.py`, foreground, PORT env default 10000, 0.0.0.0), `requirements.txt` (flask)
- `app.py` (Flask entry, blueprint registration, error handlers, per-request RLock), `db.py` (in-memory store, logical clock defaulting to exactly 2026-05-01T00:00:00Z, common fields id/created_at/updated_at/version), `errors.py` (all 29 catalog error IDs), `response.py` (scaffold envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in meta), `middleware.py` (X-User-ID/X-User-Role auth, 6 roles, DistrictBuyer/CrewLead entity-backed scope), `validation.py` (shape/FK/pagination/date helpers)
- 15 route modules + 2 service modules (`pricing.py`: coop marginal tier pricing, pinned-order closeout, warranty proration, replacement deadline; `cascade.py`: conserved-quantity recomputes for remaining_qty, total_cents, open_backorder_count/posture, booked_days, notice resolution)

**Route count:** 62 registered (method, path) pairs vs 62 scaffold endpoints — **no mismatches** (verified programmatically by diffing Flask's url_map against SCAFFOLD.yaml §1.5).

**Smoke test:** `bash start.sh` with `PORT=18746` boots clean from a fresh process, binds 0.0.0.0, answers HTTP (clock-set returns 200 with correct envelope; unauthenticated request returns `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` 400; missing resource returns `ERR_NOT_FOUND` 404), kills cleanly.

**Functional verification (57 assertions across 4 live sweeps, zero HTTP 500s):** full happy path (district → site → spec → lines → publish/close → award → accept → PO → tiered-priced lines → accept → shipment → delivery → install → VERIFIED bubble-ups → closeout 291000 with 3% early credit), marginal coop pricing across cumulative volume (870000/60000 totals), no-substitution, drawdown, duplicate PO number, fiscal cap, backorder cascade with AT_RISK posture gate and remediation exemption, OCC 412s on amendment and supersede-create, ETA forward-only loop, spec-pin staleness + amendment re-pin, damage replacement 3-link cascade (replacement deadline 2026-05-22, RESOLVED on completion), crew double-booking, site capacity with adjacency allowed, extended prorated warranty (92 days past base, 2-year extension → 50% coverage), duplicate claim. One bug found and fixed during verification (NameError in the shared install-task factory).

One spec-gap judgment call to flag: the replacement-shipment delivery of `damaged_qty` against an already-fully-delivered line would be permanently blocked by the `ERR_DELIVERY_EXCEEDS_ORDERED` check (remaining = 0), breaking the headline damage→replacement flow. I exempted REPLACEMENT-kind shipment entries from the ordered-remainder check, bounding them instead by the shipment's scheduled quantity; entries still accumulate `delivered_qty`, and claim coverage uses an `_installed_qty` snapshot taken at verification so post-verification accumulation can't inflate coverage.

Orchestrator disk verification: 27 implementation files confirmed (10 top-level + 15 route modules + 2 services); py_compile SYNTAX-OK; route parity re-verified by orchestrator after path-param normalization — 62/62, missing NONE, extra NONE.

## Step 7: Run Tests and Iterate — 2026-08-10T21:22:00.000Z

Final sweep: all 8 rounds pass 72/72 against the final artifact. Done.

## Summary

**Iterations run:** 4 sweeps total.
- Sweep 1: 71/72 in all 8 rounds — one deterministic real failure (`test_install_complete_requires_full_checklist_then_verifies_lines`).
- Sweep 2 (after test fix): the fixed test passed in all 8 rounds, but 2-3 tests per round failed on setup with "API server could not be restarted" — diagnosed as environmental: the host runs co-tenant benchmark pipelines (observed a concurrent task_1122 sweep), and measured boot time is ~0.5s idle / ~1.7s under full 8-core saturation, far inside the runner's 15s probe window. No code defect.
- Sweep 3 (with temporary start.sh boot logging for diagnosis): clean 72/72 × 8.
- Sweep 4 (final artifact, logging reverted): clean 72/72 × 8.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1125_school_furniture_public_bid_fulfillment/test_suite/test_06_install_tasks_crews_sites.py` — `test_install_complete_requires_full_checklist_then_verifies_lines`: replaced the exact-string assertion `assert line["installed_at"] == "2026-07-08T10:00:00Z"` with a format-agnostic instant comparison (`line["installed_at"].replace(".000Z", "Z") == "2026-07-08T10:00:00Z"`). Why: STEP 1b unique-derivability collapse (format silence). PRD §2.5/§3.6 verbatim-cover only that `installed_at` is "stamped from the logical clock['s full timestamp]"; PRD names "three fractional digits" only for `api_request_timestamp` (§2.2) and `created_at`/`updated_at` (§2.4), never for clock-stamped fields. A faithful PRD-only reader could serialize either `...T10:00:00Z` (matching the literal clock default string) or `...T10:00:00.000Z` (generalizing the system's timestamp convention — the implementation's choice). Per STEP 1c partial-coverage handling, the uncovered exact-format assertion was relaxed while every verbatim-covered assertion (ERR_INSTALL_CHECKLIST_INCOMPLETE, COMPLETED status, ordered `completed_checklist`, VERIFIED cascade, shipment COMPLETED, PO FULFILLED) was kept intact.

**Fixes applied to `implementation/`:** none net. `start.sh` was temporarily instrumented with per-port boot logging to diagnose the sweep-2 restart failures, then reverted byte-identical; no application code was changed.

Orchestrator disk verification: all 8 results files present, each passed=72 total=72 failed=0 errors=0 — ALL-8-CLEAN.

## Step 8: Finalize PRD — 2026-08-10T21:24:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1125_school_furniture_public_bid_fulfillment/workspace/PRD_FINALIZED.md` written with exactly one revision, tracing to the single step_7_diff item (the `installed_at` format relaxation in `test_06_install_tasks_crews_sites.py`).

**Line counts / delta:** PRD.md 322 lines (51,680 chars) vs PRD_FINALIZED.md 322 lines (51,807 chars) — 0% line delta, +127 chars (+0.25%). One line changed, in place.

**Changes:**
- §2.5 (The Logical Clock) — revise — extended the "stamped from its full timestamp" sentence to pin the serialization of clock-stamped full timestamps: "`installed_at` on a PO line and `communicated_at` on a backorder notice are stamped from its full timestamp, serialized as an ISO 8601 UTC timestamp with three fractional digits (so the default clock stamps `2026-05-01T00:00:00.000Z`)" — impl: `/home/ubuntu/github/CodingPRD/tasks/task_1125_school_furniture_public_bid_fulfillment/workspace/implementation/db.py:31-37` (`fmt_ts`/`now_ts`), writer site `/home/ubuntu/github/CodingPRD/tasks/task_1125_school_furniture_public_bid_fulfillment/workspace/implementation/routes/install_tasks.py:218`.

**Per-edit pre-edit search log:**
- Edit 1:
  - (a) Subject: serialization format of clock-stamped full-timestamp fields (`installed_at`, `communicated_at`).
  - (b) Impl paths enumerated: writers of `installed_at` — `routes/install_tasks.py:218` (`now_ts()`, the only writer; initialized `None` at `routes/po_lines.py:104`); readers of `installed_at` — `routes/warranty_claims.py:62`, `services/pricing.py:87`, `services/pricing.py:117` (all slice `[:10]`, date-prefix only, so consistent with any full-timestamp format); writers of `communicated_at` — `routes/po_lines.py:173`, `routes/po_lines.py:249`, `routes/backorder_notices.py:55` (all `now_ts()`); the single formatter — `db.py:31-37` (always three fractional digits, ms-truncated); other `now_ts()` consumers — `db.py:65`/`db.py:80` (`created_at`/`updated_at`), `response.py:12` (`api_request_timestamp`), plus `clock.py:34` (`current_utc` via `fmt_ts`). Greps: `installed_at|communicated_at`, `now_ts()`, `isoformat|strftime|.000Z|microsecond` across all of `implementation/`.
  - (c) Wording adjustment: scoped the pinned format to the two named fields only ("`installed_at` ... and `communicated_at` ... serialized as ...") rather than a universal claim about all server-emitted timestamps, so `current_utc` (`clock.py:34`, also three-fractional in impl but outside step_7_diff scope) and `updated_at` (§2.4 leaves its format unpinned) are neither contradicted nor newly pinned. `communicated_at` was included alongside `installed_at` because PRD §2.4/§2.5 name them together as clock-stamped full timestamps and the impl stamps both via the identical `now_ts()` path — pinning one but not its sibling in the same sentence would leave the sentence internally inconsistent with impl.

No other edits were made: the step_7_diff lists no test deletions, no test_helper fixes, and no net implementation changes (the temporary `start.sh` boot logging was reverted byte-identical; sweep-2 failures were environmental). All other PRD prose is already verbatim-consistent with the implementation, so it was kept intact per the minimal-patch method.

Orchestrator disk verification: PRD_FINALIZED.md present, 322 lines, diff vs PRD.md is exactly one in-place sentence revision at §2.5 (line 91).

## Step 9: Complete PRD — 2026-08-10T21:30:00.000Z

All 19 changes are in place across 18 diff hunks. The task is complete.

## Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1125_school_furniture_public_bid_fulfillment/workspace/PRD_COMPLETED.md` (copied from `PRD_FINALIZED.md`, edited in place)

**Size**: PRD_FINALIZED.md 322 lines / 51,807 chars → PRD_COMPLETED.md 322 lines / 54,411 chars. Char-delta: +2,596 (all edits are in-paragraph; line count unchanged; no new sections).

**Counts**: 16 ambiguity-pins, 3 mismatch-revisions (19 changes total).

**Ambiguity-pins** (PRD silent → pinned impl behavior):
- §2.1 — insert — ambiguity — ownership scope guards state-changing operations only; plain GET-by-id and list endpoints perform no ownership comparison — middleware.py:62-71; GET routes (e.g. routes/awards.py:95-100)
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected `ERR_INVALID_REQUEST` — validation.py:128-150
- §2.3 — insert — ambiguity — `created_at` ties break by creation order; `total_count` computed post-filter; `has_more` ⟺ offset+returned < total_count — validation.py:153-163
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — db.py:62-74
- §2.5 — insert — ambiguity — `to_iso8601` accepts a bare ISO calendar date, interpreted as midnight UTC — routes/clock.py:21-32
- §2.10 — insert — ambiguity — bubble-up requires at least one qualifying child (all-tasks-cancelled shipment never completes; no-non-cancelled-lines order never fulfills) — routes/install_tasks.py:227,242
- §3.1 — insert — ambiguity — `tier_table` must be non-empty; each row's `min_qty`/`unit_price_cents` are integers ≥ 1; rows stored as supplied (pricing selects greatest reached `min_qty`, so order is immaterial) — routes/coop_agreements.py:21-31, services/pricing.py:56-61
- §3.4 — insert — ambiguity — a cumulative unit position that has reached no tier row contributes zero cents — services/pricing.py:56-61
- §3.5 — insert — ambiguity — shipment `lines` array must be non-empty; every referenced line must belong to the named PO (`ERR_INVALID_REQUEST`); `damage_report_id` null unless cascade-created — routes/shipments.py:38-51,91-94,121
- §3.5 — insert — ambiguity — delivery `lines` array must be non-empty; entries must reference lines scheduled on this shipment (`ERR_INVALID_REQUEST`) — routes/shipments.py:179-205
- §3.6 — insert — ambiguity — `completed_checklist` starts empty — routes/install_tasks.py:79
- §3.6 — insert — ambiguity — verification retains the line's `delivered_qty` at that moment as its installed quantity (the `_installed_qty` snapshot later used for §3.9 coverage) — routes/install_tasks.py:219, routes/warranty_claims.py:75
- §3.8 — insert — ambiguity — declaration stamps the notice's `communicated_at` from the clock; the endpoint returns the updated PO line — routes/po_lines.py:168-181
- §3.8 — insert — ambiguity — supersede-create requires a non-`CANCELLED`/`VERIFIED` line and an existing open (`OPEN`/`ETA_UPDATED`) notice (`ERR_INVALID_STATE` otherwise); fresh notice stamps `communicated_at` — routes/po_lines.py:226-253
- §3.9 — insert — ambiguity — `denial_reason` and `parts_order_ref` are null at filing — routes/warranty_claims.py:87-88
- §3.9 — insert — ambiguity — enrolled district with `extended_years` 0: claims necessarily fall within the base term and are covered in full — services/pricing.py:122-124

**Mismatch-revisions** (PRD described different behavior → revised to impl):
- §3.3 (+§3.4) — revise — mismatch — "required exactly when" relaxed to "required when": a `coop_agreement_id`/`flat_unit_price_cents` supplied for the opposite pricing mode is tolerated and stored as given, and lines inherit the award's `coop_agreement_id` even under `AWARD_FLAT` if the award carries one — routes/awards.py:58-67,79-80; routes/po_lines.py:99
- §3.4 — revise — mismatch — `cancel_reason` is "accepted and ignored", not "recorded" (impl never persists it) — routes/purchase_orders.py:152
- §3.5 — revise — mismatch — the flagged judgment call: `REPLACEMENT`-kind shipment entries are exempt from the ordered-remainder check and are instead bounded by the quantity scheduled for that line on the shipment (same `ERR_DELIVERY_EXCEEDS_ORDERED`) — routes/shipments.py:218-228

**Flagged-item verification**: (1) REPLACEMENT exemption — not covered by PRD_FINALIZED.md (§3.5 pinned the remainder rule unconditionally); revised per above. (2) `_installed_qty` snapshot — §3.9 already said "delivered_qty at verification", which matches impl since `delivered_qty` cannot change after VERIFIED; I additionally pinned the snapshot explicitly at the §3.6 verification cascade.

Orchestrator disk verification: PRD_COMPLETED.md present, 322 lines / 54,411 chars; diff vs PRD_FINALIZED.md = 36 changed lines (18 hunks), consistent with the reported 19 changes.
