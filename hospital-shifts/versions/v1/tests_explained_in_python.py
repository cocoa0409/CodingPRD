"""
hospital-shifts v1 测试中最复杂的几个场景，翻译成 Python 伪代码。
目的：帮助理解测试的环境初始化流程和 ground truth 断言逻辑。

所有操作都是通过 HTTP API 完成的，不直接操作数据库。
"""

import requests

BASE_URL = "http://localhost:3000"

# ============================================================
# 三个固定的测试用户（身份通过 HTTP Header 传递，不需要预注册）
# ============================================================
CHARGE_NURSE = {"X-User-ID": "cn-1", "X-User-Role": "ChargeNurse"}
PHYSICIAN = {"X-User-ID": "physician-1", "X-User-Role": "AttendingPhysician"}
ADMIN = {"X-User-ID": "admin-1", "X-User-Role": "HospitalAdministrator"}


# ============================================================
# 通用辅助函数
# ============================================================

def post(path, payload=None, headers=None):
    """POST 请求，返回 response JSON"""
    r = requests.post(f"{BASE_URL}{path}", json=payload, headers=headers)
    return r.status_code, r.json()

def get(path, headers=None, params=None):
    """GET 请求"""
    r = requests.get(f"{BASE_URL}{path}", headers=headers, params=params)
    return r.status_code, r.json()

def put(path, payload=None, headers=None):
    """PUT 请求"""
    r = requests.put(f"{BASE_URL}{path}", json=payload, headers=headers)
    return r.status_code, r.json()

def get_data(response_tuple, expected_status=None):
    """从响应中提取 data 部分"""
    status, body = response_tuple
    if expected_status:
        assert status == expected_status, f"期望状态码 {expected_status}，实际 {status}: {body}"
    return body["data"]


# ============================================================
# 通用环境搭建函数
# ============================================================

def create_and_activate_plan(budget=250000.0):
    """
    创建一个 TreatmentPlan 并激活它。
    这是几乎所有测试的第一步。
    
    API 调用链：
    1. POST /treatment-plans              → 创建 Plan（状态=PLANNING）
    2. POST /treatment-plans/{id}/activate → 激活（状态=ACTIVE）
    """
    plan = get_data(
        post("/treatment-plans",
             {"plan_name": "Test Plan", "total_budget": budget},
             CHARGE_NURSE),
        201
    )
    activated_plan = get_data(
        post(f"/treatment-plans/{plan['id']}/activate", headers=CHARGE_NURSE),
        200
    )
    return activated_plan


def create_rotation(plan_id, name="Test Rotation", start=100, end=340):
    """
    在 Plan 内创建一个 Ward Rotation（时间段）。
    只有 ACTIVE 状态的 Plan 才能创建。
    """
    return get_data(
        post(f"/treatment-plans/{plan_id}/ward-rotations",
             {"name": name, "start_minute": start, "end_minute": end},
             PHYSICIAN),
        201
    )


def create_resource(plan_id, cost_per_minute=10.0, name="Test Resource"):
    """
    在 Plan 内创建一个 Medical Resource（医疗设备）。
    cost_per_minute 是每分钟运营成本。
    """
    return get_data(
        post(f"/treatment-plans/{plan_id}/medical-resources",
             {"resource_name": name, "resource_model": "standard",
              "operating_cost_per_minute": cost_per_minute},
             PHYSICIAN),
        201
    )


def create_procedure(plan_id, rotation_id, start, end, proc_type="Test"):
    """
    在 Rotation 内创建一个 Procedure（手术/操作）。
    start_minute 和 end_minute 定义了时间窗口。
    """
    return get_data(
        post(f"/treatment-plans/{plan_id}/ward-rotations/{rotation_id}/procedures",
             {"procedure_type": proc_type,
              "required_certification": "NONE",
              "start_minute": start,
              "end_minute": end},
             PHYSICIAN),
        201
    )


def propose_assignment(plan_id, procedure_id, resource_id, override=False):
    """
    提案：把一个 Resource 分配给一个 Procedure。
    
    这个操作会触发一系列验证：
    1. 认证匹配检查
    2. 消毒时间检查
    3. 感染风险检查
    4. 患者安全分数检查
    5. 预算检查
    6. 计算 provisional_cost
    """
    return get_data(
        post(f"/treatment-plans/{plan_id}/assignments",
             {"procedure_id": procedure_id,
              "resource_id": resource_id,
              "override_protocol_check": override},
             PHYSICIAN),
        201
    )


def approve_and_schedule(plan_id, assignment_id):
    """
    审批并确认排期。
    
    1. protocol-approve: ChargeNurse 审批通过
    2. schedule: ChargeNurse 确认排期（会重新计算 provisional_cost）
    """
    post(f"/treatment-plans/{plan_id}/assignments/{assignment_id}/protocol-approve",
         headers=CHARGE_NURSE)
    
    return get_data(
        post(f"/treatment-plans/{plan_id}/assignments/{assignment_id}/schedule",
             headers=CHARGE_NURSE),
        200
    )


def setup_plan_with_high_usage_resource(minutes_used, budget=250000, cost_per_minute=1.0):
    """
    创建一个 Plan，其中有一个 Resource 已经累计使用了 minutes_used 分钟。
    
    这是 bio-risk 测试的核心 setup：
    - 6000 分钟是 high bio-risk 阈值
    - 超过后每分钟双倍计费
    
    初始化步骤：
    1. 创建并激活 Plan
    2. 创建 Rotation
    3. 创建 Resource
    4. 如果 minutes_used > 0：创建一个 Procedure(0 ~ minutes_used)
       并提案+审批+排期，让 Resource 累计使用时间达到 minutes_used
    """
    plan = create_and_activate_plan(budget)
    plan_id = plan["id"]
    
    rotation = create_rotation(plan_id)
    resource = create_resource(plan_id, cost_per_minute)
    
    if minutes_used > 0:
        proc = create_procedure(plan_id, rotation["id"], 0, minutes_used)
        assignment = propose_assignment(plan_id, proc["id"], resource["id"])
        approve_and_schedule(plan_id, assignment["id"])
    
    return {
        "plan_id": plan_id,
        "rotation_id": rotation["id"],
        "resource_id": resource["id"],
    }


# ============================================================
# 场景一：Provisional Cost ≠ Final Cost（最经典的复杂计算测试）
# 来源：07.test.ts
# 
# 核心考点：
# - provisional_cost 使用"前瞻性"算法（把所有已知的分钟加起来）
# - final_cost 使用"按时间序"算法（按 start_minute 排序执行）
# - 同样的数据，两种算法结果不同
# ============================================================

def test_final_cost_differs_from_provisional_cost():
    """
    场景构造（1 个资源，3 个 Procedure，全在同一个 Rotation）：
    
    Resource: cost_per_minute = 10.00
    
    时间线：
    |--- baseProcedure (0~5950, 5950分钟) ---|
                                              |-- B (5980~6020, 40分钟) --|
                                                           |--- A (6050~6130, 80分钟) ---|
    
    注意：A 是先 propose 的，B 后 propose。但 B 的 start_minute < A 的 start_minute。
    
    Bio-risk 阈值 = 6000 分钟累计使用
    """
    # ====== 环境初始化 ======
    plan = create_and_activate_plan(100000.00)
    plan_id = plan["id"]
    
    rotation = create_rotation(plan_id)
    rotation_id = rotation["id"]
    
    resource = create_resource(plan_id, cost_per_minute=10.00)
    resource_id = resource["id"]
    
    # 第一步：创建 baseProcedure (5950分钟)，提案+排期
    base_proc = create_procedure(plan_id, rotation_id, start=0, end=5950, proc_type="Base")
    base_assignment = propose_assignment(plan_id, base_proc["id"], resource_id)
    approve_and_schedule(plan_id, base_assignment["id"])
    # 此时 resource 累计使用 = 5950 分钟（接近 6000 阈值）
    
    # 第二步：创建 procedureA (6050~6130, 80分钟)
    proc_a = create_procedure(plan_id, rotation_id, start=6050, end=6130, proc_type="ProcedureA")
    
    # 第三步：创建 procedureB (5980~6020, 40分钟)
    proc_b = create_procedure(plan_id, rotation_id, start=5980, end=6020, proc_type="ProcedureB")
    
    # ====== 关键操作 + ground truth 验证 ======
    
    # 提案 A 并排期
    assignment_a = propose_assignment(plan_id, proc_a["id"], resource_id)
    scheduled_a = approve_and_schedule(plan_id, assignment_a["id"])
    
    #   Provisional 计算（前瞻性）for A：
    #     资源当前已确认 = 5950 分钟
    #     A 自身 = 80 分钟
    #     总计 = 5950 + 80 = 6030 > 6000 阈值
    #     超出 = 6030 - 6000 = 30 分钟
    #     正常部分 = 80 - 30 = 50 分钟
    #     provisional_cost = 50 * 10 + 30 * 10 * 2 = 500 + 600 = 1100
    assert scheduled_a["is_high_biorisk"] == True
    assert scheduled_a["provisional_cost"] == (50 * 10.00) + (30 * 10.00 * 2.0)  # = 1100
    
    # 提案 B 并排期
    assignment_b = propose_assignment(plan_id, proc_b["id"], resource_id)
    scheduled_b = approve_and_schedule(plan_id, assignment_b["id"])
    
    #   Schedule 时重算 for B：
    #     只看 start_minute 在 B 之前的已确认 assignments
    #     B 的 start_minute = 5980
    #     baseProcedure(0~5950) 在 B 之前 → 5950 分钟
    #     A(6050~6130) 在 B 之后 → 不算！
    #     5950 + 40 = 5990 ≤ 6000，未超阈值
    #     provisional_cost = 40 * 10 = 400
    assert scheduled_b["is_high_biorisk"] == False
    assert scheduled_b["provisional_cost"] == 40 * 10.00  # = 400
    
    # ====== Finalize：触发最终成本计算 ======
    post(f"/treatment-plans/{plan_id}/initiate-final-review", headers=CHARGE_NURSE)
    post(f"/treatment-plans/{plan_id}/finalize-plan", headers=ADMIN)
    
    # 查询最终结果
    final_a = get_data(get(f"/treatment-plans/{plan_id}/assignments/{scheduled_a['id']}", CHARGE_NURSE), 200)
    final_b = get_data(get(f"/treatment-plans/{plan_id}/assignments/{scheduled_b['id']}", CHARGE_NURSE), 200)
    
    #   Final 计算（按 start_minute 时间序）：
    #     排序：baseProcedure(0~5950) → B(5980~6020) → A(6050~6130)
    #     
    #     处理 baseProcedure：累计 = 5950，未超 6000，final_cost_base = 5950 * 10 = 59500
    #     处理 B：累计 = 5950 + 40 = 5990，未超 6000，final_cost_B = 40 * 10 = 400
    #     处理 A：累计起点 = 5990，加 80 → 6070
    #       到 6000 还差 10 分钟正常价
    #       超过 6000 的有 70 分钟双倍
    #       final_cost_A = 10 * 10 + 70 * 10 * 2 = 100 + 1400 = 1500
    
    expected_final_cost_a = (10 * 10.00) + (70 * 10.00 * 2.0)  # = 1500
    expected_final_cost_b = 40 * 10.00                          # = 400
    
    assert abs(final_b["final_cost"] - expected_final_cost_b) < 0.01
    assert abs(final_a["final_cost"] - expected_final_cost_a) < 0.01
    
    # 核心验证：provisional_cost ≠ final_cost（A 的 1100 ≠ 1500）
    assert final_a["provisional_cost"] != final_a["final_cost"]


# ============================================================
# 场景二：Schedule 时 Bio-Risk 翻转
# 来源：09.test.ts
#
# 核心考点：
# - 提案时资源累计未超 6000 → not high_biorisk
# - 中间插入另一个 assignment 导致累计超过 6000
# - Schedule 时重新计算 → 翻转成 high_biorisk
# ============================================================

def test_biorisk_flips_at_schedule_time():
    """
    场景构造：
    
    Resource 初始已使用 = 5500 分钟（通过 setup_plan_with_high_usage_resource）
    
    时间线：
    |--- 已使用 (0~5500) ---|
                                     |--- B (5600~7100, 1500分钟) ---|
                                                                          |--- A (7200~7700, 500分钟) ---|
    
    操作顺序（这很关键）：
    1. 创建 A → propose → protocol-approve（但不 schedule）
    2. 创建 B → propose → approve → schedule（B 完全确认）
    3. 再 schedule A
    """
    # ====== 环境初始化 ======
    # 创建一个已经使用了 5500 分钟的 resource
    env = setup_plan_with_high_usage_resource(5500)
    plan_id = env["plan_id"]
    rotation_id = env["rotation_id"]
    resource_id = env["resource_id"]
    
    # ====== 创建 procedureA (7200~7700, 500分钟) ======
    proc_a = create_procedure(plan_id, rotation_id, start=7200, end=7700, proc_type="TypeA")
    
    # 提案 A 并审批（但暂不 schedule！）
    assignment_a = propose_assignment(plan_id, proc_a["id"], resource_id)
    post(f"/treatment-plans/{plan_id}/assignments/{assignment_a['id']}/protocol-approve",
         headers=CHARGE_NURSE)
    
    #   提案时 A 的 bio-risk 判定：
    #   已使用 = 5500，A = 500，总计 = 6000 ≤ 6000（注意：等于不算超）
    #   → is_high_biorisk = False
    assert assignment_a["is_high_biorisk"] == False
    
    # 此时安全分 = 0
    plan_before = get_data(get(f"/treatment-plans/{plan_id}", CHARGE_NURSE), 200)
    assert plan_before["patient_safety_score"] == 0
    
    # ====== 中间插入 B (5600~7100, 1500分钟) 并完全 schedule ======
    proc_b = create_procedure(plan_id, rotation_id, start=5600, end=7100, proc_type="TypeB")
    assignment_b = propose_assignment(plan_id, proc_b["id"], resource_id)
    approve_and_schedule(plan_id, assignment_b["id"])
    
    #   B 被 schedule 后：
    #   累计 = 5500 + 1500 = 7000 > 6000 → B 本身是 high_biorisk
    #   安全分 += 50 → 50
    plan_after_b = get_data(get(f"/treatment-plans/{plan_id}", CHARGE_NURSE), 200)
    assert plan_after_b["patient_safety_score"] == 50
    
    # ====== 现在 schedule A ======
    version_before = plan_after_b["version"]
    
    post(f"/treatment-plans/{plan_id}/assignments/{assignment_a['id']}/schedule",
         headers=CHARGE_NURSE)
    
    # 查询 A 的最终状态
    final_a = get_data(
        get(f"/treatment-plans/{plan_id}/assignments/{assignment_a['id']}", PHYSICIAN), 200
    )
    final_plan = get_data(get(f"/treatment-plans/{plan_id}", CHARGE_NURSE), 200)
    
    #   Schedule 时重新计算（按时间序，只看 start < A.start 的已确认）：
    #   已使用 5500 + B(1500) = 7000 > 6000
    #   A(500分钟) 全部在 6000 之后 → 全部双倍
    #   → is_high_biorisk 翻转为 True！
    assert final_a["is_high_biorisk"] == True
    
    #   安全分再 +50（因为从 not-biorisk 变成了 biorisk）
    #   50 + 50 = 100
    assert final_plan["patient_safety_score"] == 100
    
    # Plan 的 version 应该增加了
    assert final_plan["version"] > version_before


# ============================================================
# 场景三：Schedule 时产生负差价（退钱）
# 来源：09.test.ts
#
# 核心考点：
# - 提案时 A 被算成 high_biorisk（前瞻性，把所有分钟加起来）
# - Schedule 时按时间序重算，A 实际在 6000 之前 → not high_biorisk
# - 导致 provisional_cost 降低，差价退回预算
# ============================================================

def test_negative_cost_delta_at_schedule_time():
    """
    Resource: cost_per_minute = 10.00, 已使用 5500 分钟
    Budget = 100,000
    
    时间线：
    |--- 已使用 (0~5500) ---|
                             |--- B (5600~6100, 500分钟) ---|
                                                              |--- A (6200~6700, 500分钟) ---|
    
    操作顺序：
    1. 创建 A → propose → approve（不 schedule）
    2. 创建 B → propose → approve → schedule
    3. schedule A
    """
    # ====== 环境初始化 ======
    env = setup_plan_with_high_usage_resource(5500, budget=100000, cost_per_minute=10.0)
    plan_id = env["plan_id"]
    rotation_id = env["rotation_id"]
    resource_id = env["resource_id"]
    
    cost_per_min = 10.0
    
    # ====== 创建 A (6200~6700, 500分钟)，提案+审批 ======
    proc_a = create_procedure(plan_id, rotation_id, start=6200, end=6700)
    assignment_a = propose_assignment(plan_id, proc_a["id"], resource_id)
    post(f"/treatment-plans/{plan_id}/assignments/{assignment_a['id']}/protocol-approve",
         headers=CHARGE_NURSE)
    
    #   提案时 A 的计算（前瞻性）：
    #   已使用 = 5500，A = 500，总计 = 6000 ≤ 6000
    #   → is_high_biorisk = False，provisional_cost = 500 * 10 = 5000
    assert assignment_a["is_high_biorisk"] == False
    
    # ====== 创建 B (5600~6100, 500分钟)，提案+审批+schedule ======
    proc_b = create_procedure(plan_id, rotation_id, start=5600, end=6100)
    assignment_b = propose_assignment(plan_id, proc_b["id"], resource_id)
    
    #   提案 B 时（前瞻性）：
    #   已使用 = 5500，A(500) + B(500) = 1000，总计 = 6500 > 6000
    #   超出 = 500 分钟 → 双倍
    #   但 B 的 500 分钟里，哪些超了？
    #   前瞻性看：5500(已用) + 500(A) + 500(B) = 6500
    #   B 的全部 500 分钟都在 6000 之后的部分
    #   → is_high_biorisk = True，provisional_cost = 500 * 10 * 2 = 10000
    assert assignment_b["is_high_biorisk"] == True
    assert assignment_b["provisional_cost"] == 10000
    
    # 此时预算余额
    plan_before = get_data(get(f"/treatment-plans/{plan_id}", CHARGE_NURSE), 200)
    #   初始 budget = 100000
    #   已扣：setup 的 5500分钟 = 5500 * 10 = 55000
    #         A 的 provisional = 5000
    #         B 的 provisional = 10000
    #   cost_balance = 100000 - 55000 - 5000 - 10000 = 30000
    assert plan_before["cost_balance"] == 30000
    
    # ====== schedule B ======
    approve_and_schedule(plan_id, assignment_b["id"])
    
    # ====== schedule A（关键时刻！） ======
    scheduled_a_resp = post(
        f"/treatment-plans/{plan_id}/assignments/{assignment_a['id']}/schedule",
        headers=CHARGE_NURSE
    )
    scheduled_a = scheduled_a_resp[1]["data"]
    
    #   Schedule 时按时间序重算 A：
    #   只看 start_minute < A.start(6200) 的已确认 assignments
    #   已使用(0~5500) = 5500 + B(5600~6100) = 500 → 累计 6000
    #   A 从 6200 开始，累计起点 = 6000 ≤ 6000（等于不算超）
    #   → is_high_biorisk = False
    #   → provisional_cost = 500 * 10 = 5000
    assert scheduled_a["is_high_biorisk"] == False
    assert scheduled_a["provisional_cost"] == 5000
    
    # 差价 = 5000 - 10000 = -5000（退钱！）
    cost_delta = 5000 - 10000
    assert cost_delta == -5000
    
    # 预算余额应该增加了 5000
    plan_after = get_data(get(f"/treatment-plans/{plan_id}", CHARGE_NURSE), 200)
    assert plan_after["cost_balance"] == 30000 + 5000  # = 35000
    assert plan_after["cost_balance"] == 35000
    
    # 安全分不应变（A 不是 high_biorisk）
    assert plan_after["patient_safety_score"] == 0


# ============================================================
# 场景四：级联取消 + Finalization 的完整生命周期
# 来源：08.test.ts + 06.test.ts
#
# 核心考点：
# - 一个 Rotation 里有 2 个 Procedure
# - 一个被 schedule 并 assigned
# - 一个被 cancel
# - Finalization 时自动把 Rotation 标记为 COMPLETED
# ============================================================

def test_finalization_auto_completes_rotation():
    """
    场景构造：
    
    Plan (budget=5000)
      └── Rotation (0~100)
            ├── Procedure1 (0~50)  → 有 Assignment → scheduled → ASSIGNED
            └── Procedure2 (50~100) → 手动 cancel → CANCELLED
    
    流程：
    1. 创建 Plan → 激活
    2. 创建 Rotation
    3. 创建 Resource
    4. 创建 Procedure1 → 提案 → 审批 → schedule（此时 Procedure1=ASSIGNED）
    5. 创建 Procedure2 → 直接 cancel（此时 Procedure2=CANCELLED）
    6. 验证 Rotation 状态 ≠ COMPLETED（因为还没 finalize）
    7. initiate-final-review → finalize-plan
    8. 验证 Rotation 自动变成 COMPLETED
    """
    # ====== 环境初始化 ======
    plan = create_and_activate_plan(5000)
    plan_id = plan["id"]
    
    rotation = create_rotation(plan_id, "Rotation Auto", start=0, end=100)
    rotation_id = rotation["id"]
    
    resource = create_resource(plan_id, name="Test Resource")
    resource_id = resource["id"]
    
    # Procedure1：完整走完 assignment 流程
    proc1 = create_procedure(plan_id, rotation_id, start=0, end=50, proc_type="XRAY")
    assignment1 = propose_assignment(plan_id, proc1["id"], resource_id)
    approve_and_schedule(plan_id, assignment1["id"])
    # 此时 Procedure1 状态 = ASSIGNED
    
    # Procedure2：创建后直接取消
    proc2 = create_procedure(plan_id, rotation_id, start=50, end=100, proc_type="XRAY")
    post(f"/treatment-plans/{plan_id}/ward-rotations/{rotation_id}/procedures/{proc2['id']}/cancel",
         headers=PHYSICIAN)
    # 此时 Procedure2 状态 = CANCELLED
    
    # ====== 验证 finalize 前状态 ======
    rotation_before = get_data(
        get(f"/treatment-plans/{plan_id}/ward-rotations/{rotation_id}", CHARGE_NURSE), 200
    )
    assert rotation_before["status"] != "COMPLETED"  # 还没 finalize
    
    # ====== Finalize ======
    post(f"/treatment-plans/{plan_id}/initiate-final-review", headers=CHARGE_NURSE)
    post(f"/treatment-plans/{plan_id}/finalize-plan", headers=ADMIN)
    
    # ====== 验证 finalize 后状态 ======
    rotation_after = get_data(
        get(f"/treatment-plans/{plan_id}/ward-rotations/{rotation_id}", CHARGE_NURSE), 200
    )
    # Rotation 应该自动变成 COMPLETED
    # 因为它的所有 Procedure 都是终态（COMPLETED 或 CANCELLED）
    assert rotation_after["status"] == "COMPLETED"


# ============================================================
# 场景五：级联取消测试
# 来源：07.test.ts
#
# 核心考点：
# - 取消一个 Assignment 后，Procedure 回退到 PENDING
# - Rotation 不受影响（仍然是 PLANNING）
# - 预算被退回
# ============================================================

def test_cancel_assignment_reverts_procedure():
    """
    场景构造：
    
    Plan
      └── Rotation (PLANNING)
            └── Procedure → Assignment → approve → schedule → ASSIGNED
                                                                 ↓
                                                              cancel
                                                                 ↓
                                                     Procedure 回退到 PENDING
                                                     Rotation 仍然是 PLANNING
    """
    # ====== 环境初始化 ======
    plan = create_and_activate_plan()
    plan_id = plan["id"]
    
    rotation = create_rotation(plan_id)
    rotation_id = rotation["id"]
    
    resource = create_resource(plan_id)
    resource_id = resource["id"]
    
    procedure = create_procedure(plan_id, rotation_id, start=100, end=160)
    
    # 完整 assignment 流程
    assignment = propose_assignment(plan_id, procedure["id"], resource_id)
    approve_and_schedule(plan_id, assignment["id"])
    
    # 验证 Rotation 在 cancel 前是 PLANNING
    rot_before = get_data(
        get(f"/treatment-plans/{plan_id}/ward-rotations/{rotation_id}", PHYSICIAN), 200
    )
    assert rot_before["status"] == "PLANNING"
    
    # ====== 取消 Assignment ======
    _, cancel_resp = post(
        f"/treatment-plans/{plan_id}/assignments/{assignment['id']}/cancel",
        headers=CHARGE_NURSE
    )
    cancelled_assignment = cancel_resp["data"]
    assert cancelled_assignment["status"] == "CANCELLED"
    
    # ====== 验证级联效果 ======
    
    # Procedure 应该回退到 PENDING（可以重新分配）
    proc_after = get_data(
        get(f"/treatment-plans/{plan_id}/ward-rotations/{rotation_id}/procedures/{procedure['id']}",
            PHYSICIAN),
        200
    )
    assert proc_after["status"] == "PENDING"
    
    # Rotation 仍然是 PLANNING（不受影响）
    rot_after = get_data(
        get(f"/treatment-plans/{plan_id}/ward-rotations/{rotation_id}", PHYSICIAN), 200
    )
    assert rot_after["status"] == "PLANNING"


# ============================================================
# 完整的 API 调用链图（所有测试的环境初始化都遵循这个模式）
# ============================================================
"""
每个测试从零开始构建环境，调用链如下：

POST /treatment-plans                          → Plan (PLANNING)
POST /treatment-plans/{id}/activate            → Plan (ACTIVE)
  │
  ├── POST .../ward-rotations                  → Rotation (PLANNING)
  │     │
  │     └── POST .../procedures                → Procedure (PENDING)
  │
  ├── POST .../medical-resources               → Resource (无状态)
  │     │
  │     └── POST .../certifications            → 给 Resource 添加认证
  │
  ├── POST .../assignments                     → Assignment (PENDING_SCHEDULE)
  │     │                                        ↑ 此时计算 provisional_cost
  │     ├── POST .../protocol-approve          → Assignment (PROTOCOL_APPROVED)
  │     │                                        Procedure → SCHEDULED
  │     ├── POST .../schedule                  → Assignment (SCHEDULED)
  │     │                                        Procedure → ASSIGNED
  │     │                                        ↑ 此时重算 provisional_cost
  │     ├── POST .../reject                    → Assignment (REJECTED)
  │     │                                        Procedure → PENDING（回退）
  │     └── POST .../cancel                    → Assignment (CANCELLED)
  │                                              Procedure → PENDING（回退）
  │
  ├── POST .../infection-risk-pairings         → 配对两个 Resource
  │
  ├── PUT .../ward-rotations/{id}              → 更新 Rotation 状态
  │     (status=READY_FOR_ASSIGNMENT)
  │
  ├── POST .../initiate-final-review           → Plan (FINAL_REVIEW_PENDING)
  │
  └── POST .../finalize-plan                   → Plan (COMPLETED)
                                                 ↑ 此时计算所有 final_cost
                                                   Assignment → COMPLETED
                                                   Procedure → COMPLETED
                                                   Rotation → COMPLETED
"""

if __name__ == "__main__":
    print("这些函数展示了测试的环境初始化和断言逻辑")
    print("它们不是真正可运行的测试，而是 TypeScript 测试的 Python 翻译")
    print()
    print("核心要点：")
    print("1. 所有环境通过 API 调用链搭建，不碰数据库")
    print("2. 每个测试创建自己的 Plan（UUID），天然隔离")
    print("3. Ground truth 是手算的精确数值，硬编码在 assert 里")
    print("4. 操作顺序很重要：先 propose 谁、后 propose 谁，影响计算结果")
