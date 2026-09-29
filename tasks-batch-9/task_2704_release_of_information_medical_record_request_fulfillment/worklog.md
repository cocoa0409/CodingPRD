# Worklog — task_2704_release_of_information_medical_record_request_fulfillment

## Step 1: Create task directory — 2026-09-04T08:57:33.425Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2704_release_of_information_medical_record_request_fulfillment` and `.../workspace` via `mkdir -p`. Index 2704 was pre-assigned by the orchestrating prompt (no auto-allocation scan, per instruction — 32 pipelines run concurrently on this host and any scan-and-increment would collide).

## Scaffold generation complete (2026-09-04)
- SCAFFOLD.yaml (§1.0-§1.7): 2455 lines — 13 entities, 10 state-machine blocks, 2 concurrency rules, 8 calculations, 47 ordered validations, 56 endpoints, 57 errors, 8 roles.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8): 2914 lines — 9 rule_ids, 24 instances.
- SCAFFOLD_CORNER_DESIGN.yaml (§1.9): 4542 lines — 9 sections, 70 instances (50 with test_recipe, 20 excluded_because stubs).
- scaffold_lint.py: VERDICT clean lint (1205 calls scanned).

## Step 2: Generate scaffold (subagent) — 2026-09-04T10:32:08.582Z

(Note: the Step 2 subagent appended its own short section above, out of the orchestrator's format. Left in place per append-only rule. The verbatim returned summary follows.)

All three scaffold artifacts for task 2704 are complete and pass the linter cleanly.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2704_release_of_information_medical_record_request_fulfillment/`):

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2455 | 149,623 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2914 | 194,060 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4542 | 303,485 |

**SCAFFOLD.yaml counts** (§1.0–§1.7 only; verified to contain neither `scaffold_difficulty_design` nor `scaffold_corner_design`): 13 entities, 10 state-machine dimension blocks, 2 concurrency rules, 8 calculations, 47 ordered validations, 56 endpoints, 57 errors, 8 roles (3 segregation-of-duties pairs), 8 named constants. Domain `release-of-information`, prefix `/roi`, immediate consistency, cyclic state machine, complexity layers = optimistic_concurrency / dual_variant_calculation / cascading_side_effects / rate_threshold_triggers.

**Design instance counts:**
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`): all 9 §0.5 rule_ids present, **24 instances** (3/3/3/3/3/3/2/2/2).
- `SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`): all 9 guide sections present, **70 instances** — 50 with a full `test_recipe`, 20 `excluded_because` stubs that defer to a named §1.8 instance. Per section: entities 11, state_machines 12, calculations 11, validations 12, endpoints 6, errors 4, rbac 5, cross-cutting complexity layers 7, consistency model 2.

**Validation performed:** `scaffold_lint.py` → `VERDICT: clean lint` over 1205 calls (56 endpoints, 13 entities, 24 §1.8 + 50 §1.9 instances scanned). Additional scripted checks confirmed: no duplicate instance name across the two design files, every stub's `difficulty_instance` resolves to a real §1.8 name, no stub carries a `test_recipe`, and every non-stub instance has `claim_type`/`grounds`/`distinguishing_aspect`/all four recipe keys.

Two defects were caught and fixed while finishing: a `_returns_4XX` instance name (the linter's negative-name regex only matches literal digits, so it demanded a permitted role for a deliberately role-denied call — renamed to `..._rejected`), and three uses of a non-existent `IMAGING` value for `scope_categories`/`requested_categories`, replaced with `GENERAL_MEDICAL` after confirming priority 30's overlap key includes `requester_id`, so two distinct requesters never collide.

Orchestrator verification: all three files present, non-trivial (9911 lines total), `workspace/` intact (the known Step-2 task-dir-wipe hazard did not fire).

## Step 3: Copy shared files — 2026-09-04T10:32:25.368Z

`cp ./INSTRUCTION.md tasks/task_2704_release_of_information_medical_record_request_fulfillment/workspace/INSTRUCTION.md` — 1424 bytes copied.

## Step 4: Generate PRD (subagent) — 2026-09-04T10:42:42.530Z

PRD.md is complete and verified.

**Output:** `.../workspace/PRD.md` — **425 lines, 100,189 bytes**. Built incrementally (one `Write` for the opening, then seven `cat >> … <<'PRDEOF'` appends, then a script-generated §4/§5 tail), so no truncation risk.

**Section list**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (fixed verbatim); 2.3 Pagination; 2.4 Resource Identity, Timestamps and the Logical Clock; 2.5 Optimistic Concurrency: Repricing and Superseding; 2.6 Segregation of Duties Across the Release Chain; 2.7 Money, Millicents and Per-Line Rounding; 2.8 Route Resolution and Validation Precedence; 2.9 The Append-Only Compliance Trail; 2.10 Two Independent Status Dimensions on a Request
- §3 Business Logic & Workflows (9 subsections, lifecycle-ordered) — 3.1 Configuring State Fee Regimes and Onboarding Facilities; 3.2 Patients, Requesting Parties and Signed Authorizations; 3.3 Request Intake, the Access Basis, and the Statutory Clock; 3.4 Compiling the Record Set Across Source Systems; 3.5 Segregating Protected Categories and Working the Redactions; 3.6 Pricing the Released Page Set: Tiers, Caps and Forfeiture; 3.7 Release, Secure Transmission and Closure; 3.8 Denials and Their Second-Officer Review; 3.9 Amendments, Turnaround Monitoring and the Compliance Sweep
- §4 Endpoint Definitions (4-column table)
- §5 Error Code Catalogue (2-column table)

**Coverage counts measured (scripted against SCAFFOLD.yaml)**
- Endpoints: **56/56** paths present; §4 table has exactly 56 data rows, 4 columns.
- Errors: **57/57** in the §5 table and **57/57** also referenced narratively in §1–§4 — zero appear only in the table.
- Validations: **47/47** priority rules expressed; §2.8 pins the full 1→47 precedence and the three explicit conflict pairs (release state vs. unsettled invoice → `ERR_REQUEST_STATE_INVALID`; unencrypted vs. non-designated recipient → `ERR_UNENCRYPTED_DELIVERY_NOT_DIRECTED`; segregation vs. segment state → `ERR_SEGREGATION_OF_DUTIES`).
- Calculations: **8/8** expressed as precise prose with pinned evaluation order (`statutory_due_at` 5-step, `request_page_ledger` gross/net, `invoice_line_build` both variants with all 7 + 3 pinned positions, `invoice_cap_application`, `invoice_amount_due` 7-step waterfall including the cap-before-forfeiture counter-example, `turnaround_penalty` both measures, `facility_money_ledger` with its 3-way partition invariant, `segment_sensitivity_classification`).
- State machines: **10/10** blocks, all 50 transitions with from/to states, preconditions paired to error IDs, and full side-effect cascades.
- Concurrency: **2/2** OCC rules (`expected_request_version`/`ERR_STALE_REQUEST_VERSION` 412; `expected_patient_version`/`ERR_STALE_PATIENT_VERSION` 412), framed purely in stale-version terms.

**Hard contracts**
- Contract 1 (field-name coverage): entity fields 139 required / 139 present / 0 missing; endpoint inputs+outputs 110 / 110 / 0; query params 21 / 21 / 0; plus `redaction_required`, `id`, `created_at`, `updated_at`, `version`. **PASS**
- Contract 2 (rule coverage): all categories above walked, 0 missing. **PASS**
- Contract 3 (§3 path purity): 1332 backtick tokens scanned in §3 — 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. The only path token anywhere outside §4 is the `/roi` mount in §1. §3 also contains 0 markdown tables. **PASS**
- §2.2 diffs byte-identical against `section-2.2-response-structure.md`. No fuzzy/approximating words anywhere. No audit footer in the file.

**Tail:** the file ends at a clean section boundary — the final line is the last `ERR_INVOICE_UNSETTLED | 402` row of the §5 table, terminated with a newline. Nothing is cut mid-sentence and no trailing section is missing.

Orchestrator truncation check (independent): `wc -l -c` = 425 / 100189; `tail -12` shows 12 complete error-table rows ending with `| ERR_INVOICE_UNSETTLED | 402 |`; `grep '^## '` returns all five section headers (lines 3, 11, 136, 300, 363). PRD accepted — no regeneration needed.

## Step 6: Generate implementation (subagent) — 2026-09-04T11:22:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, per the skill, so the implementation generator had physical isolation from `test_suite/` — that directory did not exist at its spawn time. Step 6 returned first; its summary is recorded here.)

Implementation complete. `.../workspace/implementation/`

**Modules (3021 lines of Python, all written incrementally)**

| file | lines | role |
|---|---|---|
| `app.py` | 68 | Flask factory, 8 blueprints, ApiError/404/405/HTTPException/500 handlers, `0.0.0.0:$PORT` |
| `store.py` | 190 | constants, enums, logical clock (default `2026-08-01T00:00:00Z`), 13 empty dicts, `common_fields/touch/public/ordered` |
| `errors.py` | 74 | all 57 codes + `ERR_NOT_FOUND` / `ERR_METHOD_NOT_ALLOWED` |
| `envelope.py` | 44 | meta/object/array/error envelopes, `limit/offset/total_count/has_more` |
| `security.py` | 41 | priorities 1–3 (auth, role, requester ownership) |
| `validation.py` | 198 | priority-4 schema helpers + paging |
| `events.py` | 24 | append-only compliance trail, `occurred_at` then append order |
| `calc.py` | 338 | page ledger, `statutory_due_at`, both lateness measures, facility ledgers, line build, caps, cascades |
| `routes_config.py` | 250 | fee rules, facilities, patients, requesters, `/_clock/set_current_utc` |
| `routes_authorizations.py` | 274 | create/supersede/cure/revoke with full cascades |
| `routes_requests.py` | 437 | intake, extension, compilation, sensitive review, release, withdraw, turnaround, trail |
| `routes_segments.py` | 238 | segments, legacy-window contention, dispositions, redaction + decision |
| `routes_invoices.py` | 249 | 7-step waterfall, pinned lines, issue, settlement |
| `routes_deliveries.py` | 190 | channel safety, designated recipient, attempts, confirm/return |
| `routes_reviews.py` | 336 | denials + second-officer review, amendment requests |
| `routes_sweep.py` | 70 | compliance sweep |

**Endpoints: 56/56** — verified by enumerating `app.url_map` (list matches the PRD §4 table exactly, including `/_clock/set_current_utc`).

**Smoke test** — booted `PORT=18704 bash start.sh`, ran two scripted end-to-end scenarios over HTTP (~60 assertions, all passing), then killed the captured PID and confirmed the port free; re-booted cold on 18705 with `__pycache__` removed (200 OK) and killed that PID too. Covered: third-party retail path (auth → intake → 2 segments incl. legacy + contention refusal → compilation → sensitive review with redaction → SoD refusals → OCC 412 → invoice `subtotal 8050`, 5 lines in pinned sequence → `ERR_INVOICE_UNSETTLED` 402 on early release → issue/pay → facility ledger `collected 8050` → delivery with undesignated-recipient refusal, FAILED then SENT attempt, CONFIRMED → request CLOSED → amendment accepted, segment `amended`); and the patient-right-of-access path (30-day deadline, clock advanced 10 days late → `days_late_strict 10`/`50000`, `days_late_business 8`/`safe_harbor 30000`, `LATE_FEE_FORFEITURE` zeroing `amount_due`, `ERR_NOTHING_TO_INVOICE` on issue, void, denial → SoD → uphold-before-review refusal → overturn cascade back to COMPILATION, sweep lapsing an authorization to EXPIRED with version 2).

**Two rulings worth flagging** (conditions the scaffold states without a dedicated error code): a `delivery_format` that disagrees with the parent request's is `ERR_INVALID_REQUEST` (field constraint, checked right after the request FK); `UPHOLD` from `ISSUED` on a reviewable denial is `ERR_REVIEW_STATE_INVALID`, and the "no denial already ISSUED/UNDER_REVIEW" guard is `ERR_REQUEST_STATE_INVALID` (unreachable in practice, since an open denial always leaves the request in `DENIED`, which the origin gate already rejects).

## Step 5: Generate unit tests (subagent) — 2026-09-04T12:00:43.111Z

(Ordering note: Step 5 and Step 6 ran concurrently. Step 6 returned first and was appended above; this Step 5 entry is appended in return order, not step order, because the worklog is append-only.)

Test generation for task 2704 is complete.

## Location check (the recurring failure mode)
- `.../test_helpers/` — exists at the TASK ROOT
- `.../test_suite/` — exists at the TASK ROOT
- `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation` — no `test_helpers`, no `test_suite`

## Files and line counts
`test_helpers/`: `__init__.py` 6, `api_client.py` 200, `api_errors.py` 131, `assertions.py` 231, `constants.py` 165, `factories.py` 364, `fixtures.py` 412, `test_users.py` 93, `types.py` 39.

`test_suite/`: `conftest.py` 47, `test_01_dual_variant_calc.py` 314, `test_02_combinatorial_formula.py` 268, `test_03_non_linear_state_machine.py` 271, `test_04_transitive_cascade.py` 300, `test_05_priority_pair_validation_conflict.py` 293, `test_06_boundary_precision_check.py` 387, `test_07_cross_entity_state_dependency.py` 314, `test_08_resource_temporal_overlap.py` 325, `test_09_compensating_invariant.py` 356, `test_10_corner_entities.py` 316, `test_11_corner_state_machines.py` 266, `test_12_corner_calculations.py` 354, `test_13_corner_validations.py` 665, `test_14_corner_endpoints.py` 528, `test_15_corner_errors.py` 280, `test_16_corner_rbac.py` 482, `test_17_corner_cross_cutting.py` 428, `test_18_corner_consistency.py` 216. Total 8051 lines including helpers.

## Coverage
- **184 tests**, all collected cleanly (`pytest --collect-only -q` → "184 tests collected", no import errors).
- **74 of 74 non-stub design instances covered, 0 skipped**: queue A 24/24 (difficulty), queue B 50/50 (corner; the yaml holds 70 corner instances of which 20 are `corner_*` stubs).
- Per section: entities 11, state_machines 7, calculations 5, validations 9, endpoints 5, errors 3, rbac 4, cross-cutting 4, consistency 2; difficulty rules 3+3+3+3+3+3+2+2+2.

## Mechanical verification
- Every test function has **exactly one** `Design:` line, it is the last line of the docstring, its tag parses as `Difficulty|Corner/<section>/<name>`, and every `<name>` resolves to a real `- name:` in the two design yamls. Zero problems reported.
- Every test has exactly one `PRD: "..."` citation, and all 184 citations were verified verbatim against `workspace/PRD.md` (`checked files: 18 bad: 0`).
- `pyflakes` clean on all helper and test modules except the single intentional `test_suite/conftest.py:11 'test_helpers.api_errors' imported but unused`, which carries `# noqa: E402,F401 (registers the error/HTTP map)` and must not be "fixed".

## Design/PRD conflicts resolved in favour of the PRD (each recorded in the module it affects)
1. `test_05` `unencrypted_delivery_safety_beats_recipient_mismatch_rejected`: the design's legs 2–3 contradict §3.7 (rule 23 fires on `UNENCRYPTED_EMAIL` regardless of `encryption`), so rule 25 is isolated on a `SECURE_PORTAL` request.
2. `test_09` invoice VOID: the design's free-text void reason is not in §3.6's vocabulary; `BILLING_CLERK_VOID` used.
3. `test_13` sensitive-review completeness leg 3: the design's extra-segment `INCLUDE` would report `ERR_SENSITIVE_CATEGORY_NOT_AUTHORIZED` because §2.8 puts disclosure-safety at 20–24 ahead of completeness; driven with `WITHHOLD` instead.
4. `test_14` suspended facility: `statutory_due_at` is computed at creation per §3.4, so it is pinned to the creation value rather than the design's `null`.
5. `test_15` error envelope: `ERR_INVALID_DATE_RANGE` is 400 in §5, not the design's 422 (still a fifth distinct status).
6. `test_17` pagination: out-of-range `limit` is `ERR_INVALID_REQUEST` **400** per §2.4/§5, not 422; and because `created_at` comes from the logical clock, twelve same-instant segments share a timestamp with no PRD tie-break, so page contents are pinned against a single full-page read instead of creation order.
7. `test_18` consistency: the design's `statutory_anchor_at` field is not declared in the PRD (the anchor is `received_at`), and its "pre-accept `statutory_due_at` is null" leg contradicts §3.4, so both were adjusted.

One judgement call worth flagging for the implementation review: `test_17`'s claim that creating a PENDING record segment does **not** advance the parent request's `version` rests on §2.5's enumeration of what moves it ("every segment disposition, redaction approval, denial overturn and extension notice"), which omits segment creation — the PRD never states it outright.

Orchestrator verification: both directories confirmed at the task root; `find workspace -name test_helpers -o -name test_suite` returns nothing (the known Step-5 workspace-drift hazard did not fire); `workspace/implementation/start.sh` present.

## Step 7: Run tests and iterate (subagent) — 2026-09-04T12:36:00.000Z

Clean 8-round sweep. Summary:

## Iterations run
**2** — one diagnostic sweep (130/184 in all 8 rounds, 54 failures, perfectly deterministic — no flakiness), one confirming sweep after fixes.

## Tests deleted
**None.** All 184 tests survived. Every failure traced to a test-artifact bug or a genuine implementation defect, not to PRD silence.

## Fixes applied to `test_helpers/`

- **`assertions.py` — new `Instant` comparison wrapper** (root cause of 47 of the 54 failures). The suite asserted business datetime fields with exact string equality against second-precision literals (`"2026-08-31T00:00:00Z"`), while the implementation renders every datetime with three fractional digits (`...00.000Z`). PRD §2.2/§2.4 pin three fractional digits **only** for `meta.api_request_timestamp`, `created_at` and `updated_at`; for `received_at`, `statutory_due_at`, `released_at`, `settled_at`, `revoked_at`, `review_due_at`, `decision_due_at`, `legacy_job_end_at` etc. it fixes the *instant* and is silent on the rendering. Per STEP 1c this is partial coverage: the instant is PRD-covered, the fractional-digit rendering is not. `Instant.__eq__` compares the denoted instant, so a wrong second still fails.

- **`assertions.py` — removed `assert_page_partition`** (4 failures). It asserted `page_count_total == billable + withheld + redacted_total`. PRD §3.4 computes `page_count_total` over **all** `RETRIEVED` segments but the other three only over *releasable* (`NOT_SENSITIVE`/`AUTHORIZED_INCLUDE`) or `WITHHELD` populations — a retrieved `SEGREGATED_PENDING_REVIEW` segment is in none of them, so the four fields provably do not sum. PRD never states they do. The call was dropped from `assert_page_ledger`; the four explicit per-field expectations it wraps are untouched.

## Fixes applied to `test_suite/`

- **66 comparison sites across 15 files** rewritten from `== "<iso>"` / `!= "<iso>"` to `== Instant("<iso>")` / `!= Instant("<iso>")`, plus the import.
- **`test_13_corner_validations.py` — `_third_party_body` helper** (2 failures, both `TypeError`). It forwarded `**overrides` into `f.third_party_request_payload(...)`, which takes `authorization_id` positionally, so `_third_party_body(world, authorization_id=None)` and `(world, date_range_end=...)` raised "got multiple values for argument". Now applies overrides via `payload.update()` after the defaults, which is what the missing-authorization and shifted-bound legs actually intend.

## Fixes applied to `implementation/`

- **`routes_invoices.py`, `settle_invoice`** — removed the `if action == "PAY" and amount_cents is None: v.bad()` schema rejection. PRD §3.6 verbatim: "`amount_cents` **absent**, or present but unequal to `amount_due_cents`, is refused with `ERR_PAYMENT_AMOUNT_MISMATCH`". The implementation reported `ERR_INVALID_REQUEST` for the absent case. The existing priority-46 check now handles `None` correctly, and the invoice-state gate (priority 13) still runs first per §2.8.

No implementation check was weakened, no endpoint/field/side-effect added, storage remains in-memory only with nothing seeded.

## Final sweep, per round
| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 184/184 | 184/184 | 184/184 | 184/184 | 184/184 | 184/184 | 184/184 | 184/184 |

0 failed, 0 errors, 0 skipped in every round; 184 collected tests matches the 184 `def test_` functions in `test_suite/`, and no `skip`/`xfail` marker exists anywhere in the artifact.

Orchestrator verification (independent, not taken on the subagent's word): all 8 `results.$i.json` present (~58.7 KB each, same mtime 12:20); parsing each with `json.load` gives `passed=184 total=184 failed=0 errors=0 skipped=0` for every round; `grep -c '^def test_'` across `test_suite/*.py` sums to 184; `grep -rn 'pytest.mark.skip\|pytest.mark.xfail'` over both test dirs returns nothing. Step 8 is NOT skipped — Step 7 applied 1 `implementation/` fix plus test-layer fixes.

## Step 8: Finalize PRD (subagent) — 2026-09-04T12:40:50.933Z

PRD_FINALIZED.md written. Only two edits were warranted; the other Step 7 items were pure test artifacts or cases where PRD.md already determined behavior verbatim.

## Line counts
- `PRD.md`: 425 lines
- `PRD_FINALIZED.md`: 427 lines (+2, **+0.47%**)
- Tail verified: last line is the `| ERR_INVOICE_UNSETTLED | 402 |` row of the §5 error table. Full diff confirmed to contain exactly the two hunks below and nothing else.

## Changes
- **§2.4 — insert** — new paragraph pinning that every server-derived/stamped datetime renders as ISO 8601 UTC with exactly three fractional digits (sub-millisecond remainder truncated), enumerating the fields, and stating that client-supplied instants (`signed_at`, `expires_at`, `legacy_job_start_at`) are echoed back exactly as supplied — `implementation/store.py:85-87` (`fmt`), used at `calc.py:115,141`, `events.py:16`, `routes_requests.py:111,225,253,404,429`, `routes_reviews.py:62-63,146,153,227,297,300`, `routes_invoices.py:187,221`, `routes_deliveries.py:146,174,182`, `routes_segments.py:79,151`, `routes_authorizations.py:227,237`, `routes_config.py:250`; raw echo at `routes_authorizations.py:105-106,181-182` and `routes_segments.py:76`.
- **§3.6 "Settling" — revise** — `amount_cents` is an optional body integer declared zero-or-greater (negative/non-integer = §2.8 schema violation) but its *absence* is not a schema violation; absent or unequal still yields `ERR_PAYMENT_AMOUNT_MISMATCH` — `implementation/routes_invoices.py:202,215-218`.

## Per-edit pre-edit search log

**Edit 1 (datetime rendering)**
- (a) Subject: the wire rendering of every datetime-valued field in any response body.
- (b) Enumerated: `store.py:79-87` (`fmt`, `microsecond // 1000` truncation) and `store.py:165-180` (`common_fields`/`touch` → `created_at`/`updated_at` also via `fmt`); `envelope.py:14-18` (`api_request_timestamp`, same truncating format, wall clock); grepped every `["*_at"] =` assignment across all 16 modules and every `fmt(` callsite (list above) — all server-derived instants pass through `fmt`; grepped every `req_datetime`/`opt_datetime`/`req_date` callsite (`validation.py:140-166`) and confirmed the three client-supplied instants are persisted as the **raw** input string, and that `to_iso8601` on the clock endpoint is *not* echoed raw (`routes_config.py:248-250` returns `fmt(parsed)`); checked `routes_sweep.py` response (no datetimes) and `calc.turnaround` (`effective_completion_at` via `fmt`).
- (c) Adjustment: scoped the universal claim to datetimes "the server itself derives or stamps" and added the explicit contrasting sentence about client-supplied instants — an unqualified "every datetime field renders with three fractional digits" would have been a false universal, since `signed_at`/`expires_at`/`legacy_job_start_at` are echoed verbatim. Also wrote "among others" rather than presenting the field list as exhaustive, and referenced `created_at` for the truncation semantics so the two paragraphs cannot diverge. Deliberately said nothing about the date-only fields (`date_of_birth`, `date_range_start`/`_end`), which are also echoed raw.

**Edit 2 (settlement `amount_cents`)**
- (a) Subject: schema treatment and use of the settlement body's `amount_cents`.
- (b) Enumerated: `routes_invoices.py:197-248` (whole `settle_invoice`: `opt_int` at :202 → optional, `minimum=0`, bool/non-int rejected; state gate :208-213 at priority 13; mismatch check :217 now covering `None`; `paid_cents = amount_cents` at :225; `amount_cents` unused by the WAIVE/VOID branches); `validation.py:57-66` (`opt_int`/`_int` semantics, raising `ERR_INVALID_REQUEST` at priority 4, i.e. before the state gate, consistent with §2.8); grepped all modules for other `amount_cents` references — the only others are the invoice **line** output field (`routes_invoices.py:23-32`), which is legitimately negative for `CAP_ADJUSTMENT`/`LATE_FEE_FORFEITURE`.
- (c) Adjustment: wrote "the settlement body's `amount_cents`" rather than bare "`amount_cents`" so the zero-or-greater declaration cannot be read as contradicting the negative `amount_cents` values §3.6 already specifies for the two adjustment line types; left the WAIVE/VOID branches undescribed rather than asserting the field is ignored there.

**No-edit determinations (with their searches)**
- `assert_page_partition` removal: subject = the four page-ledger fields. Read `calc.refresh_page_ledger` (`calc.py:57-77`) against §3.4 — the impl matches the PRD's per-field definitions exactly, and the PRD never claims the four sum. A fresh implementer following §3.4 verbatim reproduces the same non-summing behavior, so no edit.
- `Instant` wrapper itself and the 66 rewritten comparison sites: same subject as Edit 1, covered by that one paragraph.
- `_third_party_body` `**overrides` `TypeError`: pure test-fixture defect in `test_suite/test_13_corner_validations.py`; no implementation behavior involved.
- `settle_invoice` implementation fix: PRD §3.6 already stated the absent-`amount_cents` outcome verbatim, so that sentence's core is kept unchanged; only the previously silent schema question was pinned.

Orchestrator verification: `cmp` confirms PRD_FINALIZED.md differs from PRD.md (2 hunks, 4 changed lines — consistent with the reported two edits); 427 lines; tail ends on the complete final §5 error-table row, so no truncation.

## Step 9: Complete PRD (3 sequential module-partitioned subagent passes) — 2026-09-04T13:11:00.000Z

Orchestrator decision (recorded per the autonomy instruction): Step 9 was run as **three sequential passes over one shared `PRD_COMPLETED.md`**, partitioned by implementation module, rather than as a single subagent. Rationale: 16 impl modules / 3021 lines of Python against a 427-line, 101 KB PRD is more surface than one subagent reliably scans; a single pass tends to return a near-identical file. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying so earlier edits could not be clobbered. Each later pass was told which distinctive earlier-pass phrase to grep for as proof the file was not reset.

Partition:
- **Pass 1** — `app.py`, `store.py`, `errors.py`, `envelope.py`, `security.py`, `validation.py`, `events.py`, `calc.py` (global/cross-cutting layer + all calculation formulas)
- **Pass 2** — `routes_config.py`, `routes_authorizations.py`, `routes_requests.py`, `routes_segments.py` (fee regimes, facilities, patients/parties, authorizations + cascades, request lifecycle, record segments)
- **Pass 3** — `routes_invoices.py`, `routes_deliveries.py`, `routes_reviews.py`, `routes_sweep.py` (money waterfall, delivery safety, denials/reviews, amendments, compliance sweep)

### Pass 1 summary (verbatim)

- Performed the `cp` from PRD_FINALIZED.md itself. Resulting line count: 427.
- PRD_FINALIZED.md 427 lines / 101,378 chars → PRD_COMPLETED.md 427 lines / 107,741 chars (**+6,363**). 15 lines rewritten, 0 added/removed. **11 ambiguity-pins, 5 mismatch-revisions.**
- §2.1 ¶1 — revise — ambiguity — whitespace-only `X-User-ID` is also `ERR_UNAUTHENTICATED`; missing/differently-cased `X-User-Role` is `ERR_UNAUTHORIZED_ROLE` — `security.py:16-21`
- §2.1 ¶4 — revise — **mismatch** — PRD claimed `FacilityAdmin` ownership checks compare `X-User-ID` against a resource's facility FK; impl has no facility ownership gate at all and never narrows a `FacilityAdmin` list — `security.py:25-41`, `routes_config.py:146`
- §2.1 ¶4 — insert — ambiguity — Requester list-narrowing applies only to whole-collection reads; a path-identified sub-resource list (invoice lines) errors `ERR_NOT_REQUEST_OWNER`; an addressed requesting party is outside the comparison — `security.py:25-32`, `routes_invoices.py:159`, `routes_config.py:217-223`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `envelope.py:9,15`
- §2.2 — insert — ambiguity — `api_request_timestamp` is the one datetime read from the host wall clock, not the logical clock — `envelope.py:13`
- §2.2 — revise — **mismatch** — the error envelope also carries the 500 from an unhandled fault, not only 4xx — `app.py:56-58`
- §2.3 ¶1 — insert — ambiguity — non-canonical `limit`/`offset` spellings are `ERR_INVALID_REQUEST`; `offset` past `total_count` is an empty page, not an error — `validation.py:174-193`, `envelope.py:34`
- §2.3 ¶2 — revise — ambiguity — default `created_at` ordering breaks ties by store append order, never by `id` — `store.py:188-190`
- §2.4 ¶3 — insert — ambiguity — clock-set `data` carries only `current_utc`, re-rendered canonically; the clock may move backwards — `store.py:70-71`, `routes_config.py:242-248`
- §2.4 ¶4 — insert — ambiguity — accepted client datetime grammar (optional seconds, 1–9 fractional digits, `T`/`t`/space, `Z`/`z`/zero offset/absent designator; any non-zero offset invalid); date-only fields strictly `YYYY-MM-DD` — `store.py:90-137`
- §2.8 ¶1 — insert — ambiguity — unmatched path → 404 `ERR_NOT_FOUND`; wrong method → 405 `ERR_METHOD_NOT_ALLOWED`; trailing slash insignificant; unhandled fault → 500 `ERR_INTERNAL` (noted as outside the §5 catalogue) — `app.py:26,37-58`
- §2.8 ¶2 — insert — ambiguity — JSON `null` counts as absent; exact non-coercive type checks incl. bool-vs-int; undeclared fields ignored; non-object body rejected; bodiless endpoints accept absent/empty/`{}` — `validation.py:13-137`
- §2.9 — revise — **mismatch** + ambiguity — PRD said every event's `days_late` equals the strict measure; impl carries it on only 6 of 10 types and 0 on the other 4, and `penalty_delta_cents` is non-zero only on the two penalty events. Also pinned the per-type `detail` `key=value` vocabulary — `events.py:8-19`, verified against all 13 `append_event` call sites
- §2.10 ¶3 — revise — **mismatch** — the "any segment write bumps the parent request's version" claim excludes segment *creation*, which touches neither the parent's `updated_at` nor its `version` — `routes_segments.py:70-92` vs `169-172,201-203,233-236`
- §3.5 — insert — ambiguity — prospective subtotal is priced from the request's current `billable_page_count`, pre-cap and pre-forfeiture, and is 0 when facility or fee rule is unresolvable — `calc.py:292-296,308-312`
- §3.9 — revise — **mismatch** — PRD said both measures re-derive "on every `fulfillment_status` transition"; impl refreshes them only on a fixed list of 12 operations and explicitly not on the DEFECT parking, the sensitive-review pass, any record-segment write or the revocation cascade, which refresh `statutory_due_at` alone — `calc.py:176-199,322-330`

Left unpinned by pass 1: `ERR_INTERNAL`/`ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED` as §5 rows (pinned in §2.8 prose instead, keeping the catalogue's final row intact; remaining 57 rows verified to match `errors.py` exactly); §3.4/§3.3's over-broad "re-derived on every transition" for the page ledger and `statutory_due_at` (both are pure functions of stored fields, so a skipped call is unobservable); `round_half_up` being half-away-from-zero (no negative value can reach it); `turnaround` degenerating to zero rates on an unresolvable fee rule (unreachable — a facility cannot onboard without one); `_breached_event` latch internals (stripped by `store.public`).

### Pass 2 summary (verbatim)

- Confirmed **no file was copied**; 24 targeted `Edit` calls only. Pass 1's edits verified intact (the `req_` id-prefix sentence, the §2.10 segment-creation exception, the §2.1 requesting-party sentence, the §2.2 wall-clock sentence). File still ends on `| ERR_INVOICE_UNSETTLED | 402 |`.
- 427 lines / 107,741 chars → 427 lines / 114,011 chars. **25 ambiguity-pins, 6 mismatch-revisions.**
- §2.3 — insert — ambiguity — declared list filters are exact string equality applied pre-pagination; undeclared query params ignored; out-of-vocabulary filter value yields an empty page, not a 400 — `routes_config.py:66-68`, `routes_requests.py:153-157`, `routes_segments.py:106-109`
- §3.1 — insert — ambiguity — `state_code` of wrong length/charset is `ERR_INVALID_REQUEST` — `routes_config.py:32-33`
- §3.1 — insert — ambiguity — facility status flip reads no current state (re-asserting the same status counts); `reason` ≤500 chars, not persisted — `routes_config.py:131-139`
- §3.2 — insert — ambiguity — `contact_email` ≤200 chars, missing at-sign is `ERR_INVALID_REQUEST` — `routes_config.py:201-204`
- §3.2 — revise — **mismatch** — `organization_name` (≤200) is not forbidden for a `PATIENT` party and `patient_id` is not forced null for non-`PATIENT` types; `credential_number` ≤100 — `routes_config.py:200-213`
- §3.2 — revise — **mismatch** — `sensitive_categories_authorized` subset relation to `scope_categories` is not enforced — `routes_authorizations.py:26-27`
- §3.2 — insert — ambiguity — `defect_reasons` order, and empty array when the only defect is an already-lapsed `expires_at` — `routes_authorizations.py:42-52`
- §3.2 — insert — ambiguity — a predecessor of a different patient / already terminal is left alone, no error, exemption still granted — `routes_authorizations.py:92,116-119`
- §3.2 — insert — ambiguity — a cure payload still computing `DEFECTIVE` reports `ERR_AUTHORIZATION_STATE_INVALID`; the cure applies no interval-ordering check — `routes_authorizations.py:169,177-179`
- §3.2 — insert — ambiguity — `revocation_reason` mandatory ≤500, not persisted — `routes_authorizations.py:219`
- §3.2 — revise — **mismatch** — revoke cascade origin set is exactly the five listed states; a request already in `AUTH_DEFECT_PENDING` is passed over (no restamp, no event, no version move) — `routes_authorizations.py:207-209,234`
- §3.2 — insert — ambiguity — a cascade segment changed in neither dimension is not touched; `redaction_applied_by_user_id` survives the reset — `routes_authorizations.py:239-249`
- §3.2 — revise — **mismatch** — `billing_status` returns to `PENDING_INVOICE` only when an invoice was actually voided — `routes_authorizations.py:255-261`
- §3.3 — insert — ambiguity — empty `requested_categories` is the §2.8 schema violation — `routes_requests.py:38-39`
- §3.3 — insert — ambiguity — intake `defect_reasons` must be an array of strings and is discarded, never persisted — `routes_requests.py:191-196`
- §3.3 — insert — ambiguity — `DEFECT` codes: `ERR_AUTHORIZATION_REQUIRED` for wrong basis, `ERR_AUTHORIZATION_STATE_INVALID` for a non-`DEFECTIVE`/absent authorization — `routes_requests.py:220-223`
- §3.3 — insert — ambiguity — a backwards-moved clock contributes zero to `tolled_seconds` rather than subtracting — `routes_authorizations.py:155-161`
- §3.3 — insert — ambiguity — `notice_note` mandatory ≤500, not persisted — `routes_requests.py:237`
- §3.3 — insert — ambiguity — `withdrawal_reason` mandatory ≤500, not persisted — `routes_requests.py:420`
- §3.4 — insert — ambiguity — segment creation reads no parent `fulfillment_status`, no tie to `requested_categories`, no (source, category) uniqueness — `routes_segments.py:45-50`
- §3.4 — revise — **mismatch** — buffered-window worked example corrected: the window ends **forty** (not fifty) minutes past; next job may not begin at or before :50, earliest whole minute :51 — `routes_segments.py:24-27`
- §3.4 — insert — ambiguity — `RETRIEVED` without `page_count` is a schema violation answered before the segment 404 — `routes_segments.py:135-138`
- §3.4 — insert — ambiguity — `unavailable_reason` optional/null, ignored on other dispositions; `page_count` forced 0 whatever was sent — `routes_segments.py:133-134,158-161`
- §3.4 — insert — ambiguity — `WITHDRAWN` leaves `page_count`, `retrieved_at` and both redaction user ids as they stood — `routes_segments.py:163-167`
- §3.5 — insert — ambiguity — an empty `segment_decisions` array is a legitimate pass when nothing is segregated; per-entry `note` ≤500 not persisted; `redaction_required` defaults false — `routes_requests.py:285-300,355-357`
- §3.5 — revise — **mismatch** — `redaction_required` on a `WITHHOLD` is ignored, and routing to `REDACTION` keys on `INCLUDE` decisions only — `routes_requests.py:360-376`
- §3.5 — insert — ambiguity — `redaction_note` ≤500 not persisted — `routes_segments.py:183`
- §3.5 — insert — ambiguity — redaction `note` not persisted, and the decision reads no parent request state (still possible after the request left `REDACTION`) — `routes_segments.py:208-224`
- §3.7 — insert — ambiguity — `release_note` ≤500 not persisted — `routes_requests.py:388`
- §3.7 — insert — ambiguity — `ERR_REDACTION_NOT_APPROVED` outranks `ERR_INVOICE_UNSETTLED` when both hold — `routes_requests.py:397-400`

Left unpinned by pass 2: state-fee-rule field mandatoriness (§3.1's "consists of" already determines it); ownership check on a nonexistent entity falling through to 404 (lives in `security.py`, pass 1's scope); per-section filter prose for the invoice/delivery/denial/amendment collections (deferred to pass 3, which the orchestrator forwarded explicitly).

### Pass 3 summary (verbatim)

- Confirmed **no file was copied**; 21 targeted `Edit` calls, no `Write`. Pass 1's marker (`req_` sentence, §2.2) and pass 2's marker ("through forty minutes past it inclusive", §3.4) both still present; file still ends on `| ERR_INVOICE_UNSETTLED | 402 |`.
- 427 lines / 114,011 chars → **427 lines / 120,183 chars**. **20 ambiguity-pins, 7 mismatch-revisions** (27 distinct locations).
- §2.5 — insert — ambiguity — `expected_request_version` is declared zero-or-greater, so a negative/non-integer is `ERR_INVALID_REQUEST` at the schema stage, not a version mismatch — `routes_invoices.py:47`
- §2.8 — revise — **mismatch** — only the sensitive-review decision list requires a segment to belong to the request; an amendment's `record_segment_id` does not — `routes_reviews.py:207` vs `routes_requests.py:314`
- §3.6 — insert — ambiguity — `ERR_INVOICE_ALREADY_EXISTS` is tested before the nothing-to-bill rule — `routes_invoices.py:59`
- §3.6 — insert — ambiguity — supersession voids *every* `DRAFT`, stamps `settled_at` and bumps the invoice `version`, and runs only after all preconditions pass — `routes_invoices.py:71`, `calc.py:334`
- §3.6 — insert — ambiguity — invoice creation increments the **request's** `version` by 1 — `routes_invoices.py:124`
- §3.6 — insert — ambiguity (pass-2 deferral) — a `Requester` list read of invoices/deliveries/denials/amendments narrows through the parent request's `requester_id`, no row carrying a requester field — `routes_invoices.py:144`
- §3.6 — insert — ambiguity — issuance tests invoice status → request state → amount due, and `amount_due_cents` ≤ 0 reports `ERR_NOTHING_TO_INVOICE` — `routes_invoices.py:175`
- §3.6 — revise — ambiguity — issuance increments both the invoice's and the request's `version` — `routes_invoices.py:191`
- §3.6 — insert — ambiguity — a `WAIVE` omitting `reason` leaves `waiver_reason` null — `routes_invoices.py:231`
- §3.6 — revise — **mismatch** — `void_reason` defaults to the literal `BILLING_CLERK_VOID`; the three-value vocabulary is what the system writes, not a validated enum, so free text of 1–500 chars is stored verbatim — `routes_invoices.py:203,237`
- §3.6 — revise — ambiguity — the `PENDING_INVOICE` assignment on `VOID` is unconditional — `routes_invoices.py:241`
- §3.6 — revise — ambiguity — every settlement increments the parent request's `version` too — `routes_invoices.py:245`
- §3.7 — insert — ambiguity — a `delivery_format` diverging from the request's is `ERR_INVALID_REQUEST`, answered after the FK resolves but before the `RELEASED` gate — `routes_deliveries.py:41`
- §3.7 — insert — **mismatch** — the one-live-transmission rule is evaluated last, after both safety rules and the designated-recipient rule — `routes_deliveries.py:72`
- §3.7 — insert — ambiguity — `failure_reason` is 1–500 chars, mandatory on `FAILED`, discarded on `SENT`, and an earlier failure's reason survives a later `SENT`; the `FAILED` branch reads no request state — `routes_deliveries.py:124,144`
- §3.7 — insert — ambiguity — `SENT` against a non-`RELEASED` request reports `ERR_REQUEST_STATE_INVALID`, tested before the attempt ceiling — `routes_deliveries.py:136`
- §3.8 — insert — ambiguity — the duplicate-open-denial guard is unreachable and would report `ERR_REQUEST_STATE_INVALID` — `routes_reviews.py:46`
- §3.8 — insert — ambiguity — `DENIAL_ISSUED` is appended before the deadline/penalty refresh, so penalty events land after it at the same `occurred_at` — `routes_reviews.py:70`
- §3.8 — revise — **mismatch** — an optional `rationale` overwrites the denial's stored `rationale` on all three actions, `START_REVIEW` included — `routes_reviews.py:137`
- §3.8 — insert — ambiguity — an `UPHOLD` straight from `ISSUED` leaves `reviewer_user_id` null — `routes_reviews.py:148`
- §3.8 — insert — ambiguity — `DENIAL_OVERTURNED` precedes the penalty re-derivation, so `PENALTY_ACCRUED` lands second — `routes_reviews.py:177`
- §3.9 — revise — **mismatch** — an amendment's segment is resolved collection-wide and need not belong to the parent request — `routes_reviews.py:207`
- §3.9 — revise — **mismatch** — the amendment `rationale` is recorded on whichever decision supplies it, `START_REVIEW` included — `routes_reviews.py:288`
- §3.9 — insert — ambiguity — `ACCEPT` re-derives no page-ledger field yet increments the segment's and the request's `version`; the event is appended whether or not the notice flag moved — `routes_reviews.py:301`
- §3.9 — insert — ambiguity — `additional_information` is mandatory, 1–500 chars; the reviewer's `rationale` survives resubmission — `routes_reviews.py:324`
- §3.9 — revise — **mismatch** — the confirmed delivery that closes a request re-derives only the facility's `penalty_exposure_cents`, not the request's two stored measures (unobservable, since they were frozen at `released_at`) — `routes_deliveries.py:178`
- §3.9 — insert — ambiguity — lapses and their events all precede the deadline work; the sweep re-derives `statutory_due_at` too; `swept_request_count` counts non-terminal requests only; the sweep moves no request or facility `version` — `routes_sweep.py:20-62`

Pass 3 closing sanity check: §4 lists **56** endpoints, §5 lists **57** errors. No dangling or contradictory prose — pass 3 re-read every paragraph it touched and repaired two of its own inserts that collided with surrounding punctuation/ordering (nested em-dashes in §3.9's amendment sentence; an ordering clause in §3.8's `OVERTURN` effect list that read against the list's own sequence).

Left unpinned by pass 3: §3.1's "all three money buckets re-derived whenever a cascade voids one" (the reprice supersession skips the ledger re-derivation, but `DRAFT` and `VOIDED` both contribute zero to all three buckets, so unobservable — and §3.1 is pass 2's territory); §3.6's `PENDING_INVOICE`→`INVOICED` wording (impl assigns unconditionally, but no reachable state lets a `DRAFT` invoice coexist with another `billing_status`); the designated-recipient comparison when a third-party authorization is unresolvable (unreachable — intake refuses such a request); `Requester` list rows whose parent request is missing (unreachable — nothing deletes a request).

### Orchestrator verification of the final artifact

- `PRD.md` 425 lines / 100,189 chars → `PRD_FINALIZED.md` 427 / 101,378 → `PRD_COMPLETED.md` 427 / 120,183.
- `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (110 changed lines across the three passes), so the scan demonstrably ran — the known "Step 9 silently no-ops" failure did not occur.
- All five section headers present (lines 3, 11, 138, 302, 365); tail ends on the complete final §5 row `| ERR_INVOICE_UNSETTLED | 402 |` — no truncation.
- §4 data rows counted independently: **56** (55 under the `/roi` prefix plus the unprefixed `POST /_clock/set_current_utc`, which matches the route the implementation actually registers). §5 error rows: **57**.
- Test/impl currency: newest `implementation/*.py` and newest `test_suite/*.py` both mtime 12:14; all 8 `results.$i.json` mtime 12:20 — the clean 184/184 × 8 sweep postdates every code change, and Steps 8–9 touched only PRD files, so the passing result still describes the shipped artifact.
- Single `worklog.md` at the task root; no strays under `workspace/`.

Pipeline complete through Step 9.
