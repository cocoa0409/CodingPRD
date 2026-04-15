"""Pre-built role headers from scaffold Table 7."""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "professor_headers": build_user_headers("test-professor-1", "Professor"),
    "student_headers": build_user_headers("test-student-1", "Student"),
    "registrar_2_headers": build_user_headers("test-registrar-2", "Registrar"),
    "professor_2_headers": build_user_headers("test-professor-2", "Professor"),
    "student_2_headers": build_user_headers("test-student-2", "Student"),
}
