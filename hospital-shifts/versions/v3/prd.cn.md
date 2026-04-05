# 医院排班系统：高级临床运营与资源生命周期管理

## 1. 执行摘要

在增强排程控制的基础上，我们正在引入全面的资源生命周期管理能力、协调的多资源操作和改进的临床准备协议。这些更新支持精密的设备退役工作流、动态资源分配以提高运营灵活性、设备特定的消毒协议、需要多个专用资源同时参与的复杂操作，以及精确的准备/收尾时间建模以提高排程准确性。

## 2. 临床准备窗口

同一设备上不同临床活动之间的无菌状态通过一个短暂的时间窗口来保持。常规设备遵循标准的三十分钟准备间隔；某些型号基于其构造和清洁流程可以适用不同的制度。创建资源配置时，`AttendingPhysician` 可以指定 `sterilization_buffer_override` 来定义该资源的特定间隔。当设置为非负整数时，此值替代标准间隔。缺失或为 null 时，适用常规的三十分钟。值为零则完全移除所需间隔；现有的重叠规则仍然适用。此窗口仅在两个操作使用同一资源且其临床类型不同时适用。

临床操作通常需要在计划开始时间之前的准备时间和计划结束时间之后的清理时间，在此期间资源被占用但并未主动运行。为了捕捉这一现实，资源配置现在包含 `setup_overhead_minutes` 和 `teardown_overhead_minutes`，分别表示准备和清理持续时间。创建资源时未指定的话，这些值默认为零。时间被建模为无界整数分钟轴；`start_minute` 和 `end_minute` 可以是任意整数。当应用资源的准备开销时，生成的 occupancy_start（计算为 `procedure.start_minute - setup_overhead_minutes`）可能为负数。所有排程验证都在这些整数分钟上操作。

我们为每个分配定义两个不同的时间窗口：

1. **操作窗口（Operational Window）**，与计划的操作持续时间完全对应。
2. **占用窗口（Occupancy Window）**，包括操作窗口加上所涉及的特定资源所需的任何前置准备时间和后续收尾时间。

同一资源上的操作不能有重叠的占用窗口，无论操作类型如何。这确保了在整个占用期间（准备、操作和收尾）的独占资源访问。

对于大多数排程目的——包括冲突检测、锁定验证和消毒缓冲要求——系统必须使用占用窗口。资源在其准备和收尾期间被视为不可用。

在计算不同类型的相邻操作之间的消毒缓冲时，所需间隔适用于第一个操作占用窗口的结束和第二个操作占用窗口的开始之间。

完整的维护保养将资源恢复到清洁状态。当维护保养记录在一个操作结束之后但不晚于同一资源上下一个操作开始之时，它满足该配对的间隔要求。操作锁定限制可用性但本身不满足无菌要求。

所有窗口使用半开区间 `[start_minute, end_minute)`。等于有效间隔的间隔是足够的；更小的间隔则不行。在第一个操作确切结束时的维护保养不满足间隔要求；它必须严格在前一个结束之后且在下一个开始之时或之前。间隔仅涉及共享的资源；其他资源不受影响。注意，现有的隔离协议仍然与计划的操作开始时间相关联，而不是占用窗口的开始。

## 3. 资产管理与生命周期更新

系统正在扩展其能力以管理医疗资产的完整生命周期，包括其最终从服务中退役。医疗资源配置现在包含一个反映其运营状态的 `status` 字段。默认情况下，新配置的资源被视为 `AVAILABLE`（可用）以供临床使用。然而，运营现实要求设备最终必须退役。`HospitalAdministrator` 可以通过 `/medical-resources/{resourceId}/decommission` 端点启动资源的退役流程。此操作阻止资源被分配到任何新的临床工作，同时允许其完成现有承诺。

如果资源没有未完成的承诺（即在任何角色中都没有处于非终态的分配），它会立即移至 `DECOMMISSIONED`（已退役）状态。这是一个终态。

如果资源仍有待处理或已排期的工作，它不能立即退役。在这种情况下，它进入 `DECOMMISSIONING_PENDING`（退役待定）状态。这表示资源将在其当前义务履行完毕后退役。

当分配被取消、拒绝、完成或重新分配离开一个资源时，系统必须评估所有涉及资源的退役完成情况。每个资源（主要和次要）必须独立检查。如果处于 `DECOMMISSIONING_PENDING` 状态的资源在任何角色中都没有剩余的非终态分配，它会自动转换为 `DECOMMISSIONED`。

`HospitalAdministrator` 可以选择撤销此决定，前提是资源仍处于 `DECOMMISSIONING_PENDING` 状态，通过调用 `/medical-resources/{resourceId}/cancel-decommissioning` 端点，将资源恢复为 `AVAILABLE` 状态。

## 4. 增强的运营灵活性

`ChargeNurse` 工作人员需要能够替换现有分配上的资源，前提是操作尚未在排程中最终确定。复杂的临床场景现在支持需要同时使用多个不同医疗资源的操作。

### 4.1. 多资源操作

系统现在支持需要同时使用多个不同医疗资源的操作。定义操作时，`AttendingPhysician` 不仅可以指定主要的 `required_certification`，还可以指定一个 `secondary_resource_requirements` 列表，指示操作持续期间所需的额外专用设备。

为此类操作提案分配时，`AttendingPhysician` 必须提供主要的 `resource_id` 以及相应的 `secondary_resource_ids` 列表。系统执行严格的协调：所有指定的资源必须在操作占用的整个持续期间同时可用且符合所有运营约束。

主要资源必须满足主要认证要求，而每个次要资源必须满足操作定义中指定的对应要求。`secondary_resource_requirements` 列表是有序的；`secondary_resource_ids` 中的第 i 个资源必须满足 `secondary_resource_requirements` 中的第 i 个认证要求。至关重要的是，参与单个操作的所有资源必须是唯一的；一个资源不能同时作为主要和次要，也不能同时履行多个次要角色。检查可用性时，系统必须考虑资源在其所有分配中的承诺，无论它是以主要还是次要身份参与。

分配资源通过在主要 `resource_id` 旁存储 `secondary_resource_ids` 来捕获此协调。

### 4.2. 分配重新分配

`ChargeNurse` 可以通过 `/assignments/{assignmentId}/reallocate` 端点将当前处于 `PENDING_SCHEDULE` 或 `PROTOCOL_APPROVED` 状态的分配重新分配给不同的 `new_resource_id`。此操作需要严格的重新验证。系统必须确保新资源是一个完全合规的替代品，满足所有现有的操作、排程和资源约束。

重新分配工作流旨在替换分配给操作的主要设备。次要资源分配在提案时被视为固定的，不能通过重新分配机制更改。重新分配多资源分配时，请求体**不得**包含 `secondary_resource_ids` 字段。如果提供了此字段，请求将以 `400 ERR_INVALID_REQUEST` 失败。重新分配时，新的主要资源不得与任何现有的次要资源相同。

重新分配过程必须被视为原子操作。如果新资源有效且财务影响可接受，则分配被更新。所有生命周期端点通过请求体中的可选 `version` 字段支持标准的乐观并发控制，遵循现有系统约定。

## 5. 财务与安全核算更新

资源替换能力和协调的多资源使用需要调整成本和安全惩罚的追踪方式。

当分配被重新分配时，其财务影响必须基于新资源的总计划工作量进行完全重新评估。系统必须在计算使用基线和阈值交叉点时考虑资源的所有已排期承诺，使用与初始分配验证期间应用的相同预测原则。

类似地，使用相同的前瞻性方法，安全影响被重新评估。`is_high_biorisk` 状态基于新资源的使用概况更新，原始资源分配中不再必要的任何生物风险惩罚必须从 `PatientSafetyScoreLedger` 退回。至关重要的是，在原始提案期间应用的任何 `PROTOCOL_OVERRIDE_PENALTY` 被视为特定于该提案和原始资源的上下文。成功重新分配后，系统必须检查此类惩罚当前是否已应用于分配；如果是，惩罚从账本退回，相关标志（`override_protocol_check` 和 `protocol_override_penalty_applied`）被重置为 false。此退回每个分配最多发生一次。

对于使用多个资源的操作，向 `CareBudgetLedger` 收取的总成本是主要资源和所有次要资源产生的运营成本的总和。每个资源的贡献独立计算，遵循其特定的运营费率、维护阈值和当前使用基线。系统必须确保只有实际的临床操作时间贡献于磨损累积和财务费用。

`PatientSafetyScoreLedger` 反映了使用超出其运营容差的任何设备所增加的风险。当分配涉及多个资源时，系统独立评估每个资源的生物风险状态。如果任何资源在操作期间处于高风险状态，标准的生物风险惩罚将应用于账本。分配的总安全影响是在操作期间每个超过其各自阈值的资源的惩罚累积。

验证提案时，系统必须考虑所有涉及资源的总潜在安全惩罚。如果此总影响会导致计划的安全分数超过阈值锁定，则提案必须被明确覆盖，遵循既定协议。

取消或拒绝多资源分配后，在其提案期间应用的所有安全分数惩罚必须完全退回。为确保对称性，系统必须确定在提案创建时哪些资源（主要和次要）超过了其维护阈值，使用当时存在的运营状态。退回必须恢复完全应用的惩罚，不受任何后续状态变更（如维护事件或额外分配）的影响。系统必须为在提案时超过其阈值的每个资源退回一个 `HIGH_BIORISK_PENALTY`。

## 6. 错误码目录

| 错误 ID | HTTP 状态码 |
| :------ | :---------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_SELF_PAIRING` | 400 Bad Request |
| `ERR_DUPLICATE_PAIRING` | 409 Conflict |
| `ERR_PROCEDURE_NOT_FOUND` | 404 Not Found |
| `ERR_PROCEDURE_NOT_PENDING_FOR_CANCEL` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_ROTATION_MINUTES` | 400 Bad Request |
| `ERR_ROTATION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_PROCEDURE_MINUTES` | 400 Bad Request |
| `ERR_PROCEDURE_NOT_PENDING` | 409 Conflict |
| `ERR_CERTIFICATION_MISMATCH` | 400 Bad Request |
| `ERR_STERILIZATION_TIME_VIOLATION` | 409 Conflict |
| `ERR_INFECTION_RISK` | 409 Conflict |
| `ERR_SAFETY_SCORE_THRESHOLD_BREACHED` | 403 Forbidden |
| `ERR_INSUFFICIENT_BUDGET` | 402 Payment Required |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED` | 409 Conflict |
| `ERR_PROCEDURE_NOT_SCHEDULED` | 409 Conflict |
| `ERR_ILLEGAL_ROTATION_STATE_TRANSITION` | 409 Conflict |
| `ERR_PROCEDURES_NOT_ASSIGNED` | 409 Conflict |
| `ERR_PLAN_NOT_READY_FOR_FINALIZATION` | 409 Conflict |
| `ERR_FINALIZATION_EXCEEDS_BUDGET` | 402 Payment Required |
| `ERR_ASSIGNMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_UNRESOLVED_ASSIGNMENTS_EXIST` | 409 Conflict |
| `ERR_PLAN_NOT_IN_PLANNING` | 409 Conflict |
| `ERR_PAIRING_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_DATA` | 409 Conflict |
| `ERR_INVALID_THRESHOLD` | 400 Bad Request |
| `ERR_PAIRING_QUARANTINE_ACTIVE` | 409 Conflict |
| `ERR_RESOURCE_ON_HOLD` | 409 Conflict |
| `ERR_RESOURCE_HOLD_NOT_FOUND` | 404 Not Found |
| `ERR_HOLD_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_HOLD_MINUTES` | 400 Bad Request |
| `ERR_HOLD_CONFLICTS_WITH_ASSIGNMENT` | 409 Conflict |
| `ERR_MAINTENANCE_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_EVENT_MINUTE` | 400 Bad Request |
| `ERR_MAINTENANCE_EVENT_CONFLICT` | 409 Conflict |
| `ERR_OVERRIDE_NOT_AUTHORIZED` | 409 Conflict |
| `ERR_OVERRIDE_NOT_REQUIRED` | 409 Conflict |
| `ERR_OVERRIDE_ALREADY_AUTHORIZED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_PENDING_OR_APPROVED` | 409 Conflict |
| `ERR_RESOURCE_DECOMMISSIONED` | 409 Conflict |
| `ERR_RESOURCE_ALREADY_DECOMMISSIONED` | 409 Conflict |
| `ERR_DECOMMISSIONING_NOT_PENDING` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_REALLOCATABLE` | 409 Conflict |
