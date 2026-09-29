# Worklog — task_2231_ladder_access_equipment_manufacturing

## Step 1: Create task directory — 2026-09-01T08:20:33.000Z

Created `tasks/task_2231_ladder_access_equipment_manufacturing/` and `tasks/task_2231_ladder_access_equipment_manufacturing/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T09:38:00.000Z

All three artifacts are complete and the lint is clean.

Output files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2231_ladder_access_equipment_manufacturing/`):
- `SCAFFOLD.yaml` (153 KB) — §1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (163 KB) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (532 KB) — single key `scaffold_corner_design`

Scaffold surface (§1.1–§1.7), calibrated above Expert (`difficulty_level: beyond_expert`):
- 15 entities, 12 state machines, 2 concurrency rules, 7 calculations, 57 ordered validation rules, 65 endpoints, 67 error codes, 9 roles
- Profile: primary `compliance_audit` + secondary `workflow_orchestration`; layers `cascading_side_effects`, `dual_variant_calculation`, `version_pinning_on_approval`, `optimistic_concurrency`, `rate_threshold_triggers`; topology `flat`; state shape `parallel` (design × market dimensions on Product); `segregation_of_duties` role model; `immediate` consistency
- Domain core: duty-rating load derivation (`RATED_LOAD_BY_DUTY` × capped safety factor with length/type/material adders), rivet & joint pull-integrity sampling with a rounded per-sample margin then averaged conformance index, periodic-audit sample sizing escalated by prior-audit failure rate, dual-basis recall exposure (shipped vs registered), gross vs mitigated design risk score, 7-year DHF retention

§1.8 difficulty design: 9 rules × 2–3 instances = 22 instances, all with full `setup_api_calls`/`trigger`/literal asserts.

§1.9 corner design: 101 entries = 86 test-recipe instances + 15 `excluded_because` stubs, across the nine guide sections — entities 13, state_machines 15, calculations 9, validations 39, endpoints 5, errors 3, rbac 9, complexity_layers 7, consistency_model 1. All `claim_type` values are drawn from the guide's per-section tables; names are unique across both design files; every stub's cited `difficulty_instance` resolves by name in the §1.8 file.

Verification: independent checks confirmed zero unbound `${var}` placeholders across both design files (setup, trigger, and asserts), zero name collisions, and no forbidden concurrency vocabulary. Two stub citations were corrected during assembly (invalid-transition release corner now cites `release_state_error_outranks_joint_safety_error`; cross-product campaign revision corner now cites `campaign_referential_error_outranks_window_overlap_error`), and one bogus `errors` stub for the stale-version codes was dropped since the two OCC corner instances trigger them directly.

Lint verdict (verbatim, `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2231_ladder_access_equipment_manufacturing`):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2231_ladder_access_equipment_manufacturing/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2231_ladder_access_equipment_manufacturing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2231_ladder_access_equipment_manufacturing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     15
  §1.8 instances scanned:     22
  §1.9 instances scanned:     86
  Calls scanned (§1.8+§1.9):  2474

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

The scenario text is stored verbatim in `SCAFFOLD.yaml`'s `scenario:` field (byte-for-byte match confirmed), and no sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-01T09:40:14.000Z

Copied `INSTRUCTION.md` to `tasks/task_2231_ladder_access_equipment_manufacturing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T09:55:44.000Z

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2231_ladder_access_equipment_manufacturing/workspace/PRD.md` — **472 lines**. The two withheld design files were never opened, and no sibling task directory was read.

## Sections covered

- **§1 Introduction** — 3 paragraphs; states the `/ladder-ops` mount and the two governing principles (compliance evidence gates commerce; containment is automatic and transitive).
- **§2 Global Specifications (10 subsections)** — 2.1 RBAC (nine roles, per-role prose, `CertificationBody` as `entity_backed:ListingBody` vs eight opaque identities, three separation-of-duty codes); 2.2 API Response Structure (verbatim paste, byte-identical, verified); 2.3 Pagination; 2.4 Record Identity, Timestamps and the Logical Clock (incl. explicit statement that load tests and joint samples carry only `id`/`created_at`); 2.5 Request Resolution Order, Collection Filters and Uniqueness (the full 57-step priority ladder + every list filter + all uniqueness keys); 2.6 Precision and Rounding Discipline; 2.7 Two Independent Product Dimensions and Cascade Discipline; 2.8 Stale-Version Guards; 2.9 Conserved Quantities (lot unit buckets, bench minutes); 2.10 Retention and Liability Dossier.
- **§3 Business Logic (9 subsections)** — cataloguing/load derivation, revision review cycle, labelling artwork, test lab (bench occupancy + load verdicts), certification listing + audit escalation, production lots/joint sampling/quarantine, design freeze + stop-ship cycle, registration/incidents/CAPA, recall exposure + closure.
- **§4** — 65-row, exactly-4-column endpoint table. **§5** — 67-row, exactly-2-column error table.

## Contract audits (all PASS)

**Field coverage check** — 143 required identifiers (135 `entities[].fields[].name` + 86 endpoint input identifiers, 78 overlapping). Two independent passes (set-difference over backticked tokens with fenced blocks stripped; per-token literal `` `name` `` search over raw text): **0 missing** on both.

**Rule coverage check** — 57/57 validation priorities stated in prose in the exact scaffold order (verified 32–57 tail against the scaffold directly); 67/67 error IDs present, all with a prose home in §2 or §3 (zero orphaned in the §5 table); 67/67 §5 HTTP statuses match the scaffold; 12/12 state machines with every from/to state token present; both OCC rules framed purely as stale-version guards (no "simultaneously"/"first-writer-wins"/"race" anywhere); all 6 calculations including both dual-variant pairs, with every numeric constant present in figures or words; the 5-hop quarantine chain and 4-hop CAPA-verify chain written hop-by-hop with causation and pinned ordering (audit failure yields `LISTING_SUSPENDED`, never `LOT_QUARANTINE`); sibling-branch symmetry covered for the `APPROVE`/`REQUEST_CHANGES` fork, the `NOT_SUBSTANTIATED`/`ROOT_CAUSE_IDENTIFIED` fork, and the `RELEASE`/`SCRAP` disposition fork; all endpoint role sets match the scaffold exactly (0 mismatches).

**Path purity check (§3 only)** — 0 backticked tokens starting with `/`, 0 bare HTTP methods, 0 method+path combinations, 0 tokens containing `/`, and 0 raw occurrences of `/ladder-ops` or any HTTP verb in §3 prose.

No pseudocode operators (`==`, `>=`, `&&`, `ceil(`, etc.) appear anywhere; no fuzzy quantifiers.

Scaffold internal contradictions were resolved toward the `endpoints`/RBAC blocks (authoritative for actors): verify → `DesignApprover`, freeze-design → `DesignApprover`, announce → `SafetyDirector`, `review_round` initial value 1. The required-test-code set is written at mechanism level (product type selects the set, `RIVETED` adds `RIVET_SHEAR`) because the scaffold supplies no per-type constant table and inventing one is forbidden.

## Step 5: Generate unit tests — 2026-09-01T11:16:59.000Z

All 16 test modules are complete and the mandatory audits pass. Final state of `/home/ubuntu/github/CodingPRD/tasks/task_2231_ladder_access_equipment_manufacturing/`:

**Stage 1 — `test_helpers/`** (9 modules): `__init__.py` (barrel), `api_client.py` (66 methods, every PRD §4 path), `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

**Stage 2 — `test_suite/`** (16 modules, 146 tests, all collected cleanly by pytest):
- Queue A (depth, `Design: Difficulty/...`): `test_01`–`test_08` = **60 tests**, covering all **22** difficulty instances with ≥2 tests each.
- Queue B (breadth, `Design: Corner/...`): `test_09` entities(13), `test_10` state_machines(13), `test_11` calculations(7), `test_12`+`test_13` validations(30), `test_14` endpoints(5)+errors(3), `test_15` rbac(9), `test_16` complexity_layers(5)+consistency_model(1) = **86 tests**, exactly one per non-stub corner instance.

**Written this session:** `test_suite/test_15_access_control.py` (9 rbac tests: unauthenticated-vs-forbidden, freeze role gate, consumer lot read, listing-body ownership mismatch, both segregation-of-duties acts, `ERR_SCRAP_REQUIRES_SAFETY_DIRECTOR`, shared joint-sample roles, owning-body grant with the three stamped instants) and `test_suite/test_16_concurrency_and_pinning.py` (6 tests: both 412 stale-version guards, product version accounting across freeze/retail-release, TIER_2 at a 40.00 % prior rate → sample size 13, frozen-pin survival past a later approval, quarantine-cascade immediacy).

**Audit results (scripted, all green):**
- Design tags: 146/146 tests carry exactly one tag, as the final docstring line; 0 untagged, 0 dual-tagged, 0 tags resolving outside the indices; 0 of the 15 `excluded_because` stubs emitted (their cross-references were verified to resolve into queue A).
- PRD citations: every quoted fragment ≥20 chars is now a verbatim substring of `workspace/PRD.md` (0 mismatches). Repairs made: stripped 28 substituted trailing periods where the PRD clause continues with `,`/`;`/`:` (test_03, 04, 06, 08, 09, 10, 12, 13, 14, 15, 16), replaced 2 non-verbatim citations with real PRD sentences (test_03's cooldown-strictness clause; test_10's `ERR_REVISION_STATE_INVALID` sentence from §3.2, also replacing a truncated §2.5 ladder quote in two tests).
- Imports: 0 missing and 0 unused `test_helpers` names across `test_suite/`; no test uses the lenient `get_success_data`; all files compile.
- 66 distinct error IDs asserted, every one named in PRD prose (not just the status table). No `skip`/`xfail`/`TODO`; no mention of "scaffold" in generated code (only the domain enum `MOBILE_SCAFFOLD_TOWER`).

**Instances skipped for PRD-first failure: none** — all 22 difficulty and 86 non-stub corner instances passed the coverage + unique-derivability filter. Where a scaffold instance carried a non-derivable detail, only that detail was dropped, not the test: `JOINT_DESIGN_DEFECT` replaced by the PRD's `RIVET_SHEAR_MARGIN` (instances 52, 76), `SUBMITTED` replaced by `UNDER_REVIEW` (54), the per-`product_type` `ELECTRICAL_LEAKAGE` requirement omitted (50), and instance 82's "documents did not bump the product version" claim omitted since the PRD does not uniquely derive it.

## Step 6: Generate implementation — 2026-09-01T11:16:59.000Z

Implementation complete and verified.

## Files created
All under `/home/ubuntu/github/CodingPRD/tasks/task_2231_ladder_access_equipment_manufacturing/workspace/implementation/` (3,835 lines of Python, no data files on disk):

Infrastructure
- `start.sh` (executable) — `cd` to its own dir, guarded `pip install` (only if `import flask` fails, to avoid contention across per-test reboots), then `exec python3 app.py`
- `requirements.txt` — `Flask>=3.0.0`
- `app.py` — app factory, blueprint mounting at `/ladder-ops`, `POST /_clock/set_current_utc`, per-request mutex, and error handlers for `ApiError` / 404 / 405 / unhandled
- `store.py` — 15 in-memory dicts + logical clock (`2026-08-01T00:00:00Z`), idempotent `commit()` that applies one `version` bump + `updated_at` restamp per mutated entity per request
- `errors.py`, `response.py` (envelope + pagination meta), `auth.py` (`X-User-ID`/`X-User-Role`, 9 roles), `validate.py` (typed field/enum/instant/pagination/filter/sort helpers), `calc.py` (all 6 calculation rules + constants), `serialize.py` (15 serializers with pinned field order), `lookup.py` (typed 404 resolvers + scans), `cascade.py` (risk score, DHF retention, quarantine 5-hop, audit-failure 4-hop, CAPA-verification 4-hop, recall announce, stop-ship/resume-ship)

Routes (`routes/`): `__init__.py`, `_common.py`, `products.py`, `design_revisions.py`, `product_documents.py`, `lab.py`, `production.py`, `listings.py`, `consumers.py`, `incidents.py`, `recalls.py`

## Endpoints
65 routes registered: 64 under `/ladder-ops` (matching the scaffold endpoint table exactly) plus `POST /_clock/set_current_utc`.

## Verification
1. Fresh boot: `PORT=10124 bash start.sh` came up on `0.0.0.0`; `GET /ladder-ops/products` returned 401 `ERR_UNAUTHENTICATED` without headers, and with headers returned `total_count: 0` for products, production-lots, recall-events and field-incidents with `api_request_timestamp` `2026-08-01T00:00:00.000Z` — proving the empty, unseeded store and the deterministic clock on every relaunch. Only `__pycache__` is ever written (removed); no DB/JSON files.
2. End-to-end smoke suite (`/tmp/smoke_ladder.py`, ~130 assertions) against a fresh boot: **ALL SMOKE CHECKS PASSED**. It exercised product derivation (`safety_factor` 4.45, `required_test_load_lb` 1335, deflection 1.6), revision submit/review with segregation of duties, all 6 document kinds + label rules, bench cooldown conflict, campaign start/load-tests/conclude for DESIGN_QUALIFICATION + CERTIFICATION_LISTING + PERIODIC_AUDIT, freeze-design, listing grant (`audit_due_at`, `listing_expires_at`), release-to-retail, lot production/samples/`conformance_index`/release, registrations, incident → investigate → resolve → CAPA → verify (risk 36.0 → mitigated 9.0, auto-close, auto resume-ship, listing restore), the audit-failure cascade (listing SUSPENDED → product STOP_SHIP `LISTING_SUSPENDED` → lot QUARANTINED 900 units → registration hold → `held_registration_count` 1), disposition RELEASE → resume-ship → listing re-LISTED, recall draft/announce/notify/acknowledge/close with both exposure bases, the liability dossier, and the `TestBench.reserved_minutes_total == sum(duration_minutes)` invariant. It also confirmed 14 negative paths land on the right error id/status (409 duplicates, 403 role/ownership/SoD, 400 pagination + window + future date, 412 both OCC checks, 422 business constraints).

Two smoke-test expectations I had written were wrong and the implementation was right (verified against scaffold §1.3): `margin_pct` rounds to whole percent per sample before averaging (`conformance_index` 2.50, not 2.775), and a tie between lot-release and recall anchors resolves to `LOT_RELEASE`.

## Documented assumption
The required load-test code set per `product_type` is not specified in PRD.md or SCAFFOLD.yaml (only the forbidden design file would have it). `calc.REQUIRED_TEST_CODES_BY_PRODUCT_TYPE` encodes: `STATIC_VERTICAL` + `RAIL_BENDING` + `SLIP_RESISTANCE` for every type, plus `HINGE_CYCLE` for `ARTICULATED_LADDER`, plus `RIVET_SHEAR` when the pinned revision's `joint_type` is `RIVETED`; `ELECTRICAL_LEAKAGE` is never required. This is the one place where hidden tests could diverge.

## Step 7: Run tests and iterate — 2026-09-01T11:27:40.000Z

All 8 parallel rounds pass 146/146.

## Summary

**Iterations run:** 2 (sweep 1 → diagnose/fix → sweep 2 clean)

**Sweep 1 result:** 144/146 in all 8 rounds — 2 tests failed deterministically in every round (no flakiness observed; both were real implementation defects).

**Tests deleted:** none. Both failures traced to verbatim PRD sentences and passed STEP 1a coverage + STEP 1b unique derivability, and both fixtures/factories were PRD-consistent (STEP 2), so both went to STEP 3 implementation fixes.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**

`/home/ubuntu/github/CodingPRD/tasks/task_2231_ladder_access_equipment_manufacturing/workspace/implementation/routes/production.py` — `disposition_production_lot()`, two defects in the same function:

1. The `RELEASE` branch never reset `quarantine_reason_code`, so a released lot kept reporting the stale reason (`LABEL_DEFECT`). PRD §3.6: *"Choosing `RELEASE` is the compensating action for quarantine: it moves the lot `QUARANTINED` → `RELEASED` … sets `disposition` to `RELEASE`, clears `quarantine_reason_code` to null"*. Added `lot["quarantine_reason_code"] = None` on that branch.

2. The `SCRAP` branch cleared no consumer holds and never recomputed the model counter — hold-clearing was implemented only inside the `RELEASE` branch. PRD §3.6: *"Scrapping moves the lot `QUARANTINED` → `SCRAPPED` … sets `disposition` to `SCRAP`, clears `hold_flag` to false on every consumer registration of the lot, and recomputes the model's `held_registration_count`."* Hoisted the registration hold-clearing loop and `cascade.recompute_held_registration_count(product)` out of the `RELEASE` branch so both dispositions run them, matching the PRD, which states the identical clause for each branch.

Both fixes are additive PRD-required behaviour; no implementation check was removed or weakened, and no assertion was relaxed.

Orchestrator verification: all 8 `results.{1..8}.json` confirmed `passed == total == 146`.

## Step 8: Finalize PRD — 2026-09-01T11:30:31.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2231_ladder_access_equipment_manufacturing/workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md 472 lines / PRD_FINALIZED.md 472 lines — 0% line delta (both edits are in-paragraph, on single long lines 278 and 280); 2 of 472 lines revised (~0.4% of lines touched).

Both Step 7 fixes moved the implementation *toward* existing PRD text, so the PRD prose that the fixes cite (§3.6 `RELEASE` clears `quarantine_reason_code`; both dispositions clear holds and recompute `held_registration_count`) was kept **verbatim**. The only patches pin two residual choices the impl makes at the very lines those fixes touched, which PRD.md left open.

**Changes**
- §3.6 (`RELEASE` disposition) — revise — the hold-clearing loop applies to every registration of the lot regardless of `registration_status`, and only rewrites registrations whose `hold_flag` is currently true, so an already-clear registration is not version-bumped — `implementation/routes/production.py:287-291` (loop guarded by `if registration["hold_flag"]`), `implementation/store.py:84-108` (`mark_dirty`/`commit` is what turns a touch into a `version` increment).
- §3.6 (`SCRAP` disposition) — revise — `SCRAP` retains `quarantine_reason_code` (only `RELEASE` clears it), and its hold-clearing follows the same terms as `RELEASE` — `implementation/routes/production.py:278-291` (no `quarantine_reason_code` write on the else-branch; shared loop below it).

**Per-edit pre-edit search log**

Edit 1 — subject: clearing `hold_flag` on a lot's consumer registrations, and which entities get a `version` bump as a result.
- (b) Paths enumerated/read: `grep -rn hold_flag` over all of `implementation/` → every hit examined: `routes/production.py:285-291` (disposition, shared by both branches), `cascade.py:246-251` (quarantine hop one, sets true, also skips rows already true), `cascade.py:95-102` (`recompute_held_registration_count`, iterates `registrations_of_product`, always `mark_dirty(product)`), `routes/consumers.py:42-65` (creation-time hold when lot is `QUARANTINED`, then recompute), `routes/consumers.py:83` (`hold_flag` collection filter), `serialize.py:238`; plus `lookup.registrations_of_lot`/`registrations_of_product` (`lookup.py:119-128`), and `store.py:84-108` (`mark_dirty`, `commit` — at most one bump per entity per request, new records exempt). Also checked PRD §2.4 line 94 and §2.7 line 140 for any pre-existing no-op/version rule (none).
- (c) Adjustment: added "whatever that registration's `registration_status`" because `registrations_of_lot` is unfiltered on the clearing side while quarantine hop one (PRD line 276) sets the flag only on `REGISTERED`/`NOTIFIED` — without it the sentence could be read as inheriting hop one's status filter. Deliberately scoped the "left untouched / keeps its `version`" clause to registrations only, so it does not contradict `recompute_held_registration_count`, which version-bumps the product unconditionally even when the count is unchanged. Left the quarantine hop-one sentence untouched (it is silent, not wrong).

Edit 2 — subject: `quarantine_reason_code` lifecycle across dispositions.
- (b) Paths enumerated/read: `grep -rn "quarantine_reason_code"` over all of `implementation/` → the only writers are `routes/production.py:76` (create, null), `cascade.py:242` (quarantine sets it from the supplied/system reason), `routes/production.py:276` (`RELEASE` clears it); readers `serialize.py:179`. Confirmed no scrap-side, recall-side, or stop-ship-side clearing exists (also checked `cascade.py` audit-failure and stop-ship/resume arms, `routes/recalls.py` via the same grep — no hits).
- (c) Adjustment: phrased as "leaves … at the value the quarantine recorded rather than clearing it" instead of naming a specific code such as `AUDIT_FAILURE`, since the retained value can be any of the four operator codes or the system `AUDIT_FAILURE`. Attached the hold-clearing cross-reference to the `hold_flag` clause only ("on the same terms as a `RELEASE` disposition") so it cannot be read as importing `RELEASE`'s quality gates, which the `SCRAP` branch does not run.

## Step 9: Complete PRD — 2026-09-01T11:39:18.000Z

**Files**: `workspace/PRD_FINALIZED.md` (472 lines / 88,230 chars) → `workspace/PRD_COMPLETED.md` (473 lines / 93,630 chars); **char delta +5,400**, one net new line (a bullet in §2.2).

**Counts**: 28 inline edits across 27 lines — **22 ambiguity-pins**, **6 mismatch-revisions**. No new sections; every change is an in-paragraph insert or rewrite.

- §2.1 — insert — ambiguity — auth rejects an *empty* header value, not just an absent one — `auth.py:28`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case alphanumerics — `response.py:14`
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall clock — `response.py:27`
- §2.2 — insert — ambiguity — pagination meta absent on single-resource responses; `has_more` formula pinned — `response.py:59`
- §2.2 — insert — ambiguity — transport fallbacks `ERR_NOT_FOUND` 404 / `ERR_METHOD_NOT_ALLOWED` 405 use the same envelope — `app.py:67-83`
- §2.3 — insert — ambiguity — empty-string `limit`/`offset` take defaults — `validate.py:222`
- §2.3 — insert — ambiguity — `created_at` ties break by creation order; pagination precedes filtering; null field never matches an equality filter — `_common.py:9-13`, `validate.py:272`
- §2.4 — insert — ambiguity — records are born at `version` 1 with `updated_at == created_at`; creation is not a mutation; at most one bump per record per request — `store.py:105-127`
- §2.4 — insert — ambiguity — clock endpoint answers 200 with `data` holding only `current_utc`, and accepts a backwards instant — `app.py:36-42`
- §2.5 — insert — ambiguity — boolean filters accept `true`/`false`/`1`/`0`; empty filter values ignored — `validate.py:262-272`
- §2.6 — insert — ambiguity — client-supplied engineering figures are stored/echoed verbatim (no re-quantization); numerics serialize as JSON numbers so trailing zeros vanish — `serialize.py:8-13`, `routes/products.py:40`
- §2.10 — insert — ambiguity — `approved_document_kinds` is ordered by the canonical `doc_kind` declaration order — `routes/products.py:267`
- §2.10 — insert — ambiguity — dossier is a computed read with no `id`/`created_at`/`updated_at`/`version` — `routes/products.py:263-276`
- §3.2 — insert — ambiguity — `reviewer_notes` is written null when omitted, overwriting a prior round's notes — `routes/design_revisions.py:148`
- §3.2 — insert — ambiguity — revise leaves `reviewed_by_user_id`, `reviewer_notes`, `superseded_at` untouched — `routes/design_revisions.py:178-187`
- §3.4 — insert — ambiguity — `duration_minutes` drops the part-minute remainder; reservation is not gated on campaign status — `routes/lab.py:100`
- §3.4 — insert — ambiguity — **the per-`product_type` required test-code sets were entirely absent from the PRD**; now pinned (three codes for STEP/EXTENSION/PLATFORM/MOBILE_SCAFFOLD_TOWER, +`HINGE_CYCLE` for ARTICULATED, `ELECTRICAL_LEAKAGE` never required) — `calc.py:142-153`
- §3.5 — revise — mismatch — grant-listing gate order corrected to state → design-frozen → qualifying campaign → standard-accredited — `routes/listings.py:116-143`
- §3.5 — insert — ambiguity — a PASSED audit re-stamps `audit_due_at` whatever the record's own status — `routes/lab.py:412-417`
- §3.5 — revise — mismatch — audit-failure hop three is not gated on hop two: the lot is quarantined even when the listing was already out of `LISTED` — `cascade.py:276-281`
- §3.6 — insert — ambiguity — quarantine hop one skips registrations already flagged, so their `version` is unchanged — `cascade.py:246-250`
- §3.6 — insert — ambiguity — a null `conformance_index` at disposition fails `ERR_CONFORMANCE_BELOW_MINIMUM`, not `ERR_NO_JOINT_SAMPLES` — `routes/production.py:263-270`
- §3.6 — insert — ambiguity — neither disposition resumes shipment; the model stays `STOP_SHIP` — `routes/production.py:287-291`
- §3.7 — revise — mismatch — release-to-retail gate order corrected to state → document set → design-frozen → active listing — `routes/products.py:160-184`
- §3.8 — insert — ambiguity — registering onto a `QUARANTINED` lot does not fire the quarantine chain; `market_status` is untouched — `routes/consumers.py:62-65`
- §3.8 — revise — mismatch — the `ROOT_CAUSE_IDENTIFIED` branch *does* run the risk recomputation (bumping product `version`) even though the values cannot change — `routes/incidents.py:145-147`
- §3.8 — insert — ambiguity — a corrective action's `design_revision_id` is not scope-checked against the incident's model — `routes/incidents.py:162-171`
- §3.9 — revise — mismatch — a drafted recall has `units_remedied`/`units_outstanding` at 0 (not null), and `affected_revision_ids` members are opaque, unresolved strings — `routes/recalls.py:31,51-52`
- §3.9 — revise — mismatch — announcement checks recall state *before* product market status and names `ERR_PRODUCT_STATE_INVALID` (previously unnamed), an explicit exception to the §2.5 ladder — `routes/recalls.py:81-89`
- §3.9 — insert — ambiguity — withdrawal retains `listed_at`, `listing_expires_at`, `suspended_at`, `suspension_reason` — `cascade.py:378-382`

Note on the two order revisions in §3.5/§3.7: the implementation already matched the §2.5 priority ladder; it was the section prose that enumerated the gates in a conflicting order, so the prose was rewritten rather than the ladder. The only genuine ladder deviation in the implementation is recall announcement, pinned inline in §3.9.
