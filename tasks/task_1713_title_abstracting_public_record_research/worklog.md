# Worklog — task_1713_title_abstracting_public_record_research

## Step 1: Create Task Directory — 2026-08-14T10:02:00.000Z

Directory `tasks/task_1713_title_abstracting_public_record_research/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions.

## Step 2: Generate Scaffold — 2026-08-14T10:45:00.000Z

All three scaffold artifacts are generated and verified. Final report:

## Task complete — task_1713_title_abstracting_public_record_research

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1713_title_abstracting_public_record_research/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys), verbatim scenario text
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`, 18 instances (exactly 2 per rule × 9 rules)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`, 49 active instances + 8 `excluded_because` stubs

**Design summary**
- Archetype: workflow_orchestration (secondary: compliance_audit); flat topology, cyclic state machines, approval-chain roles (Client/Abstracter/Examiner/OperationsManager, all `opaque` with attribute ownership via `client_ref`/`abstracter_ref`/`reviewer_examiner_ref`), immediate consistency.
- 7 entities (AbstractOrder, SearchAssignment, RecordDocument with self-referential `prior_document_id` chain-of-title links, LegalDescriptionCheck, AbstractReport, CurativeRequirement, CountyRetrieval), 42 endpoints (the scenario spans 8 distinct workflow areas, so the surface runs above the Advanced guideline band — density is in the coupling, not CRUD), 29 error codes, 7 state machines, 7 calculations, 21 ordered validations, 2 OCC concurrency rules on `AbstractOrder.version` (PATCH scope amendment + report creation).
- Rule highlights: provisional-vs-final order fee (75000 vs 54688) vs per-page/per-document retrieval fee (Rule 1); liability-cap nested `min` + tier branch vs pinned subtotal-level rush-premium rounding (51406 vs the 51407 per-line trap) (Rule 2); cyclic revision loops on SearchAssignment and AbstractReport (Rule 3); depth-4 deliver cascade and depth-2 flag→curative cascade (Rule 4); (state, business_safety) and (business_temporal, business_constraint) priority pairs (Rule 5); inclusive scope-start date boundary and strict `>` SLA due_at boundary with literals 0 vs 5000 credit (Rule 6); report×curative and order×legal-check gates (Rule 7); half-open abstracter windows vs 30-minute buffered examiner slots (Rule 8); fee post/reverse and document create/void conservation invariants (Rule 9).
- Logical-clock test-driving endpoint `POST /api/_clock/set_current_utc` with the mandated startup default `2026-08-01T00:00:00Z`.

**Verification**
- `scaffold_lint.py` verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (42 endpoints, 7 entities, 18 + 49 instances, 436 calls scanned)
- All formula-derived assert literals re-executed in Python and confirmed (75000/54688/164064, 51406, 53125/50000 restore, 50000/5000/45000, 150000/200000 caps).
- No forbidden concurrency vocabulary; every §1.6 error is wired to a validation and exercised by at least one instance.
- Two ordering subtleties were caught and fixed during replay: fee lifecycle guards (priority 5) now precede the order-terminal guard (priority 6) so `ERR_ALREADY_INVOICED` is reachable post-delivery, and the parent-terminal guard precedes generic child-state checks so `ERR_ORDER_TERMINAL` fires correctly on cancelled orders.

## Step 3: Copy Shared Files — 2026-08-14T10:46:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1713_title_abstracting_public_record_research/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T10:50:00.000Z

That one "missing" item is a false positive from my regex grabbing a description fragment ("County charging mode: PER_DOCUMENT") — the actual enum values `PER_DOCUMENT` and `PER_PAGE` are both present in §3.9. All 79 literals verified.

Now a careful manual walk of Contract 2's six high-risk categories against the PRD text I wrote:

**1. `validations[].priority` ordering** — §2.10 states the full ordering explicitly: auth (401) → authorization (403) → well-formedness (400) → existence (404) → fiscal lifecycle guards → terminal-order guard → generic state legality (409) → domain business rules, with the observable-precedence example (`ERR_ALREADY_INVOICED` never masked by `ERR_ORDER_TERMINAL`). §3.5 enumerates submission's four checks in order; §3.7 enumerates report-open's three conditions; §3.9 restates the fiscal-guard precedence. ✓

**2. `concurrency_rules[]`** — both rules expressed in §2.8 and again in §3.2 (PATCH) and §3.7 (report create): write endpoint named via capability, `expected_abstract_order_version` required, mismatch → `ERR_STALE_VERSION` (HTTP 412). No time-overlap framing used. ✓

**3. Cross-entity side effects** — cancel cascade (§2.9, §3.10: assignments → CANCELLED, report → CANCELLED, FEE_POSTED → FEE_REVERSED + fee recompute, version bump), deliver cascade (§2.9, §3.10: report APPROVED → DELIVERED → retrievals FEE_POSTED → INVOICED → final fee/late credit/billed/cap recompute, version bump), flag cascade (§3.4: auto-CurativeRequirement with severity rule + `open_curative_count` increment), resolve cascade (§3.6: overwrite `legal_description_text`, clear `legal_hold`, version bump, guard re-evaluation). ✓

**4. `applies_to` scopes** — ERR_WINDOW_INVALID applies to both assignment creation and start-review: both covered (§3.3 window, §3.7 slot names `ERR_SLOT_INVALID`; scaffold priority 10 names both endpoints with their respective error ids — window→`ERR_WINDOW_INVALID`, slot→`ERR_SLOT_INVALID`, both stated). OCC rule's two endpoints both covered. Fiscal guards' two endpoints covered. ✓

**5. Field-level structured content** — defaults stated: `sla_tier`/`liability_tier`/`severity`/`fee_mode` default STANDARD/PER_DOCUMENT, `exception_applies` default false, nulls-until-set for `delivered_at`/`final_fee_cents`/`billed_fee_cents`/`return_reason`/`revision_reason`/`reviewer_examiner_ref`/`review_slot_start`/`review_slot_end`/`resolution_note`/`resolved_description`/`fee_cents`, zero-initials for counters, `revision_count`/`revision_number` increment semantics, `state_code` constraint, `search_period_years` 1..60 range, `page_count` >= 1 requirement. ✓

**6. Sibling-branch symmetry** — both verdict branches (VERIFIED/MISMATCH) specified with equal density; both waiver safety checks; both retrieval fee branches with the 10-page example; cancel-from-each-state enumerated; all six from-states of cancel named in §3.10. ✓

**Tail** — every state machine transition (order's 10 transitions incl. 6 cancel siblings, assignment's 7, document's 4, check's 3, report's 9, curative's 2, retrieval's 3), all 7 calculations (provisional quote with the 40000/8×2500/25% formula and RUSH-vs-STANDARD initialization asymmetry, retrieval_fee with both branches and the worked example, actualization with the pinned rounding-order worked example, liability cap with both multipliers and the 200000 ceiling, SLA 72/24 hours + 10% late credit + strict-greater lateness + exact-at-due_at on-time, document_scope with both-inclusive bounds, chain_break with trim + case-sensitive comparison), all 21 validations mapped to error ids in §2/§3 prose, and all endpoint side effects. The `to_iso8601` clock input and the `2026-08-01T00:00:00Z` startup default are in §2.5. ✓

All three hard contracts pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1713_title_abstracting_public_record_research/workspace/PRD.md`.

---

**Done.** Generated `/home/ubuntu/github/CodingPRD/tasks/task_1713_title_abstracting_public_record_research/workspace/PRD.md` (~42 KB) from the scaffold, without opening either forbidden design-index file.

**Structure chosen** (domain-derived, not templated):
- §2: 10 subsections — access control with opaque-identity prose for all four roles, the verbatim §2.2 envelope block, pagination, common resource properties, the logical clock & SLA, monetary precision & fee ledger (incl. the pinned rush-premium rounding order with the 10281-vs-10282 worked example), liability limits, OCC, cascading finalization, and nested-resource/validation ordering.
- §3: 10 subsections organized by engagement chronology (intake → amendment → dispatch → recording → search closure → legal description QC → report review → curative list → county fees → cancellation/delivery), with parameters scattered across subsections and no endpoint paths or HTTP methods anywhere in §3 backticks.
- §4: 4-column endpoint table (41 rows). §5: 2-column error catalogue (29 errors).

**Hard contract reports:**

```
Field coverage check:
- entities[].fields: 60 required, 60 present, 0 missing
- endpoints[].request_body/input: 44 required, 44 present, 0 missing
- endpoints[].query_params: 12 required, 12 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 21 checked, 21 expressed (ordering stated in §2.10 + per-endpoint sequences in §3.5/§3.7/§3.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint capability + expected_abstract_order_version + ERR_STALE_VERSION/412 each), 0 missing
- state_machines[].transitions: 41 checked (7 state machines incl. cancel siblings and system cascades), 41 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed in precise prose (constants embedded: 40000/2500/125/8/25%/72h/24h/10%/×3/×5/200000), 0 missing
- validations[] conditions: 21 checked, 21 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 41 endpoints checked, all side effects and multi-endpoint scopes expressed, 0 missing
- entities[].fields[] structured content: 60 checked, defaults/null-until/increment semantics reconstructible, 0 missing
- sibling-branch symmetry: 8 groups checked (verdicts, waiver checks, fee branches, cancel from-states, etc.), 8 symmetric, 0 asymmetric
- enum/state/role/error literals: 79 verified present (the one checker-flagged item was a regex false positive on a description fragment; PER_DOCUMENT/PER_PAGE both present)
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 376
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

One verification note: my initial mechanical check produced a nonsense "4 present" result because the four ` ``` ` code fences in the verbatim §2.2 block break naive backtick pairing; stripping fenced blocks first resolved it and both mechanical contracts then passed cleanly.

## Step 6: Generate Implementation — 2026-08-14T11:05:00.000Z

Implementation complete. All files are in `/home/ubuntu/github/CodingPRD/tasks/task_1713_title_abstracting_public_record_research/workspace/implementation/`.

## What was built

A Python + Flask REST API for the Title Abstracting & Public Record Research PRD, structured per the skill's mandated layout:

- `start.sh` — guarded dependency install (no-op `pip install` once Flask is present, safe for per-test-server reboots) and `exec python3 app.py` in the foreground
- `app.py` — blueprint registration, ApiError/404/405/400/500 envelope handlers, binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory dict store (starts **empty** on every boot, no seeding), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, common fields (`id` UUID, `created_at`/`updated_at` with 3 fractional digits, `version` starting at 1)
- `errors.py` / `response.py` / `middleware.py` — exact scaffold error catalog, `meta`/`response_type`/`data` envelope with `req_` ids, `X-User-ID`/`X-User-Role` auth (401 undeclared/missing, 403 wrong role)
- `util.py` — strict body shape validation (`ERR_VALIDATION`), ISO date/datetime parsing (timestamps truncated to the second per PRD), Decimal round-half-up money, `limit`/`offset` pagination (default 10, min 1, max 100)
- `routes/` — one module per resource group (orders, assignments, documents, checks, reports, curatives, retrievals, clock), all 41 endpoints
- `services.py` — fee ledger, liability cap, SLA/scope/chain calculations, read-time computed fields, search-completion guard

## Key fidelity decisions

- **Validation priority order** from scaffold §1.4 is enforced literally, including fiscal-audit precedence (`ERR_FEE_ALREADY_POSTED`/`ERR_ALREADY_INVOICED` fire *before* `ERR_ORDER_TERMINAL`) and `ERR_SCOPE_LOCKED` (p19) before `ERR_STALE_VERSION` (p21).
- **Pinned rounding order**: rush premium computed once on the whole subtotal (verified: 3×375-cent lines → premium 10281, accrued 51406).
- **Derived-at-read fields** (`is_overdue`, `legal_hold`, `open_curative_count`, `document_count`, `verified_count`, `in_scope`) computed on read so PATCH scope changes, clock sets, and cascades never leave stale values; order `version` bumps on every stored-field mutation (including fee posts/reverses, cascades).
- **Boundary semantics**: inclusive scope window, half-open assignment windows (touching allowed), exactly-30-minute review-slot gap allowed, delivery exactly at `due_at` is on time, case-sensitive trimmed chain-break comparison, Feb-29-safe calendar-year subtraction.

## Verification

Two smoke suites (78 checks total) passed against the live server covering the full workflow: order intake quotes (STANDARD/RUSH, EXTENDED cap ceiling), window overlap/invalid, chain-of-title linkage, flag→CRITICAL curative→satisfy, return/resume loop, legal-hold blocking and clearing search completion, OCC-guarded report open (412), buffered review slots, SoD waiver (403), open-curative approval block, fee post/reverse compensating pair, late delivery credit (42500 → 4250 credit → 38250 billed), cancel cascade with fee reversal, and client read isolation. Cold-restart via `start.sh` confirmed an empty store and the default logical clock, satisfying the per-test-server isolation contract.

## Step 5: Generate Unit Tests — 2026-08-14T11:24:00.000Z

Generation complete. Final report:

## What was generated

**Stage 1 — `test_helpers/`** (9 modules, ~1400 lines):
- `types.py` — 7 entity TypedDicts (all carry `id/created_at/updated_at/version` per PRD §2.4 "none omits updated_at or version"), 7 status enums, role/tier/type enums
- `api_client.py` — `ApiClient(GenericApiClient)` with 34 methods, one per PRD §4 endpoint (incl. `POST /api/_clock/set_current_utc`)
- `api_errors.py` — all 29 error IDs with HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_order_fee_invariants` (billed = final − credit; cap ≤ 200000)
- `factories.py`, `constants.py` (40000/2500/125/8/25%/10%/3×/5×/200000/72h/24h/30min, clock default `2026-08-01T00:00:00Z`)
- `test_users.py` — all four roles are opaque (PRD §2.1); `make_<role>_headers(ref)` builders thread X-User-ID to recorded refs (`client_ref`/`abstracter_ref`/`reviewer_examiner_ref`), plus `NO_AUTH_HEADERS`
- `fixtures.py` — 5-tier composites: `drive_order_to_search_complete`, `drive_report_under_review`, `drive_order_ready_for_delivery` (accepts `retrieval_specs` to pre-post fees; retains `order_at_creation` snapshot for OCC tests), `setup_delivered_order`

**Stage 2 — `test_suite/`** (conftest + 9 files, **84 tests**):
- **Queue A (Difficulty): 36 tests — exactly 2 per each of the 18 instances** (variants split into primary-outcome + side-effect tests)
- **Queue B (Corner): 48 tests — 1 per non-stub instance**; all 10 `excluded_because:` stubs skipped with cross-refs verified to resolve

## PRD-first adjudication decisions

- **Skipped (sanctioned gap):** `Corner/entities/order_create_computed_field_input_ignored` — the PRD never states that client-supplied values for computed fields are ignored; a strict-validation implementation rejecting the unknown field with `ERR_VALIDATION` (§3.1) is PRD-faithful, so the asserted 201+60000 outcome is not uniquely derivable. No placeholder emitted.
- **One relaxed assertion:** `Corner/validations/second_active_report_rejected` asserts HTTP 409 + `validate_error_is_one_of([ERR_REPORT_ALREADY_ACTIVE, ERR_INVALID_STATE])` — an active report necessarily means the order left `SEARCH_COMPLETE`, so both rules always co-fire and PRD §2.10's ordering does not uniquely pin which a faithful reader surfaces.
- Version literals are never hard-coded (`version == 1`); OCC tests use captured-creation-version + relative increments since PRD §2.4 doesn't pin the initial value numerically.

## Audits (all clean)
py_compile + pyflakes clean; all modules import under `PYTHONPATH=.`; **verbatim-citation audit**: 238 citation slices grep-verified against `workspace/PRD.md` (7 boundary-punctuation drifts found and fixed); **C4 audit**: every test docstring ends with exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line resolving to a real instance; **coverage audit**: 18/18 difficulty ×2, 48/48 corner ×1; zero `skip`/`xfail` markers; zero scaffold references in comments.

## Step 7: Run Tests and Iterate — 2026-08-14T11:40:00.000Z

All 8 rounds clean: 84/84 passed, 0 failed, 0 errors in every round. Exiting with the summary.

## Summary

**Iterations run: 2** (sweep 1: 78/84 in all 8 rounds, 6 deterministic failures; sweep 2 after fix: 84/84 in all 8 rounds)

**Tests deleted: none.** Every failing assertion traced to verbatim PRD prose with unique derivability intact.

**Fixes applied to `test_helpers/`: none.** Fixtures, factories, and role-header builders were audited end-to-end (STEP 2) and found faithful to PRD — correct ownership threading (`X-User-ID` == `client_ref`/`abstracter_ref`/`reviewer_examiner_ref`), correct payload shapes, correct per-PRD preconditions.

**Fixes applied to `implementation/` (2 files, 1 root cause):**

All 6 failures (`test_order_creation_applies_defaults_and_computed_fields`, `test_deliver_finalizes_fee_ledger_and_liability_cap`, `test_deliver_response_reflects_full_cascade_immediately`, `test_delivery_exactly_at_due_at_earns_no_late_credit`, `test_delivery_one_second_past_due_at_earns_ten_percent_credit`, `test_scheduled_clock_drives_is_overdue`) were the same defect: clock-stamped domain fields were rendered with millisecond precision (`2026-08-01T00:00:00.000Z`) instead of the clock's exact second-precision reading (`2026-08-01T00:00:00Z`).

- `/home/ubuntu/github/CodingPRD/tasks/task_1713_title_abstracting_public_record_research/workspace/implementation/db.py` — added `fmt_ts_sec(dt)` rendering `%Y-%m-%dT%H:%M:%SZ` (second precision). Rationale: PRD §2.5 states "the logical clock reads exactly `2026-08-01T00:00:00Z`", "The logical clock stamps `received_at`… stamps `delivered_at`…", and "All timestamp comparisons in this domain are made to the second"; the "three fractional digits" rule in §2.2/§2.4 is scoped verbatim to `api_request_timestamp`, `created_at`, and `updated_at` only.
- `/home/ubuntu/github/CodingPRD/tasks/task_1713_title_abstracting_public_record_research/workspace/implementation/routes/orders.py` — `create_order` (received_at, due_at), `patch_order` (due_at re-derivation), and `deliver_order` (delivered_at) now stamp via `db.fmt_ts_sec` instead of `db.fmt_ts`.

`created_at`/`updated_at`/response-meta timestamps deliberately kept at three fractional digits per PRD §2.2/§2.4. No endpoints, fields, or checks were added or removed; storage remains in-memory only; no data is seeded at startup.

Orchestrator note: the subagent's results files were not persisted at its reported paths, so the orchestrator re-ran the full 8-round sweep itself after the subagent exited; all 8 rounds confirmed 84/84 passed, 0 failed, 0 errors, and `results.1.json`–`results.8.json` are now present in `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-08-14T11:42:00.000Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1713_title_abstracting_public_record_research/workspace/PRD_FINALIZED.md`.

**Line counts / delta:** PRD.md 259 lines, PRD_FINALIZED.md 259 lines (0% line delta — the single edit extends line 78 in place; one sentence appended to the §2.5 first paragraph, no new sections).

**Changes (one total):**

- **§2.5 (The Logical Clock and Turnaround SLA) — insert** — appended one sentence pinning that clock-stamped/clock-derived timestamps `received_at`, `due_at`, and `delivered_at` render in ISO 8601 UTC to the second with no fractional digits (e.g. `2026-08-01T00:00:00Z`), and explicitly scoping the three-fractional-digit format of §2.2/§2.4 to only `api_request_timestamp`, `created_at`, `updated_at` — impl: `implementation/db.py:56-64` (`fmt_ts_sec`), call sites `implementation/routes/orders.py:83-84` (create: received_at, due_at), `orders.py:163` (patch: due_at re-derivation), `orders.py:209` (deliver: delivered_at); ms-format kept at `db.py:46-53`, `db.py:69`, `db.py:83`, `response.py:13`.

**Per-edit pre-edit search log (edit 1 of 1):**

- (a) **Subject:** serialization precision of logical-clock-stamped domain timestamps (`received_at`, `due_at`, `delivered_at`) versus the millisecond audit/meta timestamps.
- (b) **Impl paths enumerated and read/grepped:** `grep -rn "fmt_ts|fmt_ts_sec|strftime|isoformat|microsecond"` and `grep -rn "db.now()|parse_dt|dt_of_stored|window_start|window_end|review_slot"` over all of `implementation/`. Full enumeration: `db.py` (fmt_ts, fmt_ts_sec, new_entity, touch), `response.py:13` (api_request_timestamp), `routes/orders.py:83,84,163,209,225` (stamp + read-back of the three fields), `services.py:152` (is_overdue compares via `dt_of_stored` on `due_at`), `util.py:21-57` (`parse_dt`/`dt_of_stored` truncate to whole seconds), `routes/clock.py:21,24` (clock set parses via `parse_dt`; `current_utc` echoes the client's raw string), `routes/assignments.py:69-89` and `routes/reports.py:142-164` (window/slot instants stored as raw client strings, compared via `parse_dt`). Also verified no PRD example anywhere renders `received_at`/`due_at`/`delivered_at` with fractional digits.
- (c) **Wording adjustment:** named the three fields explicitly rather than saying "all timestamps the clock stamps" universally, so the sentence does not reach `current_utc` (raw echo in clock.py:24) or the client-supplied `window_start`/`window_end`/`review_slot_*` strings (echoed verbatim in assignments.py:88-89, reports.py:163-164); used "stamped and clock-derived" to cover both `received_at`/`delivered_at` (direct stamps) and `due_at` (derived at create and re-derived at patch, both via `fmt_ts_sec`); added the trailing scoping clause so the sentence reaffirms — rather than implicitly broadens — the existing §2.2/§2.4 three-digit rule, matching `fmt_ts` usage at `db.py:69`, `db.py:83`, `response.py:13`.

**Why only one edit:** the Step 7 diff's single root cause was exactly this rendering-precision silence; all other diff items (the six failing tests) were manifestations of it, fixtures/test_helpers were audited faithful, and no tests were deleted. Every other behavior the diff touched (created_at/updated_at/meta timestamps at ms) was already pinned verbatim by §2.2/§2.4 and matches the implementation, so no further wording was needed.

## Step 9: Complete PRD — 2026-08-14T11:53:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1713_title_abstracting_public_record_research/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md` (259 lines / 42,567 chars → 262 lines / 46,955 chars; +3 lines, +4,388 chars, 21 edited passages, no new sections).

**Counts:** 15 ambiguity-pins, 6 mismatch-revisions.

**Changes (per passage):**

- §2.2 — insert — ambiguity — `api_request_timestamp` pinned as stamped from the logical clock — implementation/response.py:10-14
- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`, negative/non-integer `offset` → `ERR_VALIDATION` (400); `created_at` sort ties broken by creation (insertion) order; `total_count`/`has_more` semantics; exact filter sets per list endpoint, unknown query params ignored — implementation/util.py:150-198, implementation/db.py:93
- §2.4 — insert — ambiguity — `version` starts at 1; `created_at`/`updated_at` stamped from the logical clock — implementation/db.py:67-83
- §2.5 — insert — ambiguity — clock set unconditionally (need not advance), truncated to the second; endpoint returns 200 with `current_utc` echoing the supplied string verbatim — implementation/routes/clock.py:16-24, implementation/util.py:21-36
- §2.8 — revise — mismatch — OCC rule changed from "advanced past the supplied value" to exact-equality comparison (any version mismatch → `ERR_STALE_VERSION`) — implementation/routes/orders.py:141-142, implementation/routes/reports.py:81-82
- §2.9 — insert — ambiguity — terminal guard covers child *creation* as well as mutation — implementation/routes/assignments.py:67, documents.py:92, checks.py:62, reports.py:75, curatives.py:59, retrievals.py:66
- §2.10 — insert — ambiguity — request-shape rules: JSON-object bodies, unknown/missing/invalid fields → `ERR_VALIDATION` (400); explicit null on optional field means absent; absent body = empty object — implementation/util.py:76-135
- §2.10 — revise — mismatch — attribute-ownership 403s that read a stored resource are enforced after that resource resolves (404 precedes ownership refusal); only endpoint-role and body-attribute (order-placement `client_ref`) checks run at the 403 stage before 400 — implementation/routes/orders.py:70-78,175-177, assignments.py:118-122, documents.py:79-92, reports.py:170-176
- §3.1 — insert — ambiguity — Feb 29 effective dates clamp to Feb 28 of the target year for `scope_start_date` — implementation/services.py:64-72
- §3.2 — revise — mismatch — amendment re-derivation of `in_scope` covers *all* recorded documents (VOID included) via read-time derivation, not just non-VOID — implementation/services.py:182-186, orders.py:160-166
- §3.3 — insert — ambiguity — window endpoints stored/returned verbatim; dispatch requires only an existing non-terminal order — implementation/routes/assignments.py:66-67,88-89
- §3.4 — insert — ambiguity — `order_id`/`assignment_id` resolved independently (no same-order requirement); duplicate-instrument check precedes chain-link validation; flag takes a mandatory `reason`; void `reason` not persisted — implementation/routes/documents.py:52-54,85-102
- §3.4 — revise — mismatch — voiding does *not* require the assignment to be `IN_PROGRESS` (only verify/flag do); PRD previously claimed all three dispositions did — implementation/routes/documents.py:181-194
- §3.6 — insert — ambiguity — verdict payload requires both `verdict` and `survey_exception_applied` — implementation/routes/checks.py:37-40
- §3.7 — revise — mismatch — report opening and draft submission require only the Abstracter role (no assignment-ownership check; report records no abstracter), not "the assigned Abstracter" — implementation/routes/reports.py:69-71,114-117
- §3.7 — insert — ambiguity — slot endpoints echoed verbatim; require-revision retains `reviewer_examiner_ref`/slot until a later booking overwrites — implementation/routes/reports.py:162-167,190-208
- §3.8 — revise — mismatch — any abstracter may satisfy a requirement (no `abstracter_ref` check; requirements aren't assignment-tied), not "the assigned abstracter" — implementation/routes/curatives.py:90-102
- §3.8 — insert — ambiguity — `record_document_id` on a direct raise must exist but need not belong to the named order — implementation/routes/curatives.py:56-58
- §3.9 — revise — mismatch — retrieval requests open to any abstracter (no assignment-ownership check); named document must exist but need not belong to the order, no document-status precondition — implementation/routes/retrievals.py:59-66
- §3.9 — revise + insert — mismatch + ambiguity — `page_count` with `PER_DOCUMENT` is stored/echoed but fee-irrelevant (was "ignored"); each post/reverse bumps the parent order's `version` and `updated_at`; reversal `reason` not persisted — implementation/routes/retrievals.py:45-47,67-77,117-141
- §3.10 — insert — ambiguity — cancellation `reason` accepted but not persisted — implementation/routes/orders.py:63-65,170-197
- §5 — insert — ambiguity — added `ERR_NOT_FOUND` (404) catalogue row as the framework-level fallback for undeclared paths/methods — implementation/app.py:40-46
